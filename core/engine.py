import zipfile
import xml.etree.ElementTree as ET
import networkx as nx
import oracledb
import re
import sys

class TririgaHybridEngine:
    def __init__(self, db_username, db_password, db_dsn, offline_mode=False):
        self.graphs = {} 
        self.queries = {}
        self.db_conn = None
        self.cursor = None
        self.workflow_metadata = {}
        self.loaded_workflow_names = [] 
        self.offline_mode = offline_mode
        # Live-lookup memoization: the same Module/BO/Association names and spec records are
        # validated repeatedly across dozens of nodes. Caching collapses O(nodes x keys) round
        # trips down to O(distinct lookups).
        self._validation_cache = {}
        self._record_payload_cache = {}
        
        if not self.offline_mode:
            self._connect_to_oracle(db_username, db_password, db_dsn)
        else:
            print("SUCCESS: Engine initialized in OFFLINE mode. (Live Oracle Database bypassed).")

    def _connect_to_oracle(self, username, password, dsn):
        try:
            print(f"Establishing live connection to Oracle Database at {dsn}...")
            self.db_conn = oracledb.connect(user=username, password=password, dsn=dsn)
            self.cursor = self.db_conn.cursor()
            print("SUCCESS: Live Database Connection Established.\n")
        except Exception as e:
            print(f"CRITICAL: Failed to connect to Oracle. The engine will be blind to live data.\nError: {e}")
            sys.exit(1)

    def _get_type_str(self, data):
        t = data.get('type', data.get('Type', 'Generic'))
        if isinstance(t, list): return str(t[0])
        return str(t).strip()

    def _strip_namespaces(self, xml_payload):
        """Make an XML payload namespace-agnostic before parsing.

        TRIRIGA OM Package exports are inconsistent about XML namespaces. Rather than
        stripping only the first ``xmlns`` (which silently breaks the moment a payload
        declares a default namespace plus any prefixed ones), we remove ALL namespace
        declarations and element/attribute prefixes so ElementTree's plain ``find``/
        ``findall`` calls keep matching bare tag names.
        """
        # Remove every namespace declaration (default and prefixed).
        cleaned = re.sub(r'\sxmlns(:\w+)?\s*=\s*"[^"]*"', '', xml_payload)
        # Strip prefixes from opening and closing element tags: <ns:Tag> -> <Tag>.
        cleaned = re.sub(r'(</?)[\w.-]+:', r'\1', cleaned)
        # Strip prefixes from attribute names: ns:attr="..." -> attr="...".
        cleaned = re.sub(r'(\s)[\w.-]+:([\w.-]+\s*=)', r'\1\2', cleaned)
        return cleaned

    def get_branch_map(self, node_data):
        """Map each raw TargetAssociation task id of a branching task to its branch label.

        TRIRIGA encodes branch routing across two parallel fields:
            TargetAssociation = "333546;333395;"   (ordered branch target task ids)
            EventName         = "0=true;1=false;"   (branch index -> truth value, Switch only)

        Switch (Type 14) branches are labeled 'TRUE'/'FALSE'. Iter (Type 24) tasks use the
        exact same TargetAssociation mechanics but carry loop semantics: the FIRST id is the
        LOOP BODY (run once per record) and the SECOND is the EXIT taken when the record set
        is exhausted -- so those branches are labeled 'LOOP BODY'/'EXIT'.
        """
        t_type = self._get_type_str(node_data)

        targets = node_data.get('TargetAssociation', '')
        if isinstance(targets, list): targets = targets[0] if targets else ''
        target_list = [t for t in str(targets).split(';') if t]

        if t_type == '24':
            labels = ['LOOP BODY', 'EXIT']
            return {str(tgt): (labels[i] if i < len(labels) else 'EXIT')
                    for i, tgt in enumerate(target_list)}

        event = node_data.get('EventName', '')
        if isinstance(event, list): event = event[0] if event else ''

        index_truth = {}
        for token in str(event).split(';'):
            token = token.strip()
            if '=' in token:
                idx, val = token.split('=', 1)
                idx = idx.strip()
                val = val.strip().lower()
                if idx.isdigit():
                    index_truth[int(idx)] = 'TRUE' if val in ('true', '1', 'yes') else 'FALSE'

        truth_map = {}
        for i, tgt in enumerate(target_list):
            if i in index_truth:
                truth_map[str(tgt)] = index_truth[i]
            else:
                # Positional fallback only when EventName is absent/malformed for this index.
                truth_map[str(tgt)] = 'TRUE' if i == 0 else 'FALSE'
        return truth_map

    def get_switch_truth_map(self, node_data):
        """Backwards-compatible alias; see get_branch_map."""
        return self.get_branch_map(node_data)

    def get_node(self, task_id):
        for wf_name, graph in self.graphs.items():
            if graph.has_node(str(task_id)):
                return graph.nodes[str(task_id)], wf_name
        return None, None

    def fetch_retrieved_spec_ids(self, wf_name, task_id):
        if not self.cursor or wf_name not in self.graphs or not self.graphs[wf_name].has_node(str(task_id)):
            return []
        
        node_data = self.graphs[wf_name].nodes[str(task_id)]
        t_type = self._get_type_str(node_data)
        
        if t_type == '22':
            filter_bo = node_data.get('FilterBo', [])
            q_name = filter_bo[0] if isinstance(filter_bo, list) and filter_bo else (filter_bo if isinstance(filter_bo, str) else None)
            if not q_name or q_name not in self.queries: return []
            
            q_data = self.queries[q_name]
            bo_name = q_data.get('BO')
            if not bo_name or bo_name == 'Unknown BO': return []
            
            clean_bo = re.sub(r'[^a-zA-Z0-9_]', '', bo_name).upper()
            table_name = f"TRIDATA.T_{clean_bo[:26]}"
            
            sql = f"SELECT SPEC_ID FROM {table_name} WHERE 1=1"
            params = {}
            
            for i, f in enumerate(q_data['Filters']):
                field_name = f['Field'].split('::')[-1].upper()
                op = f['Operator']
                val = f['Value']
                
                param_key = f"val{i}"
                if op == 'Equals':
                    sql += f" AND {field_name} = :{param_key}"
                    params[param_key] = val
                elif op == 'Does Not Equal':
                    sql += f" AND {field_name} != :{param_key}"
                    params[param_key] = val
                elif op == 'Contains':
                    sql += f" AND {field_name} LIKE :{param_key}"
                    params[param_key] = f"%{val}%"
                    
            try:
                self.cursor.execute(sql, params)
                rows = self.cursor.fetchall()
                return [str(r[0]) for r in rows]
            except Exception as e:
                print(f"\n[Dynamic SQL Error in Query Task]: {e}")
                return []
                
        elif t_type == '29':
            bo_name = node_data.get('BO')
            if isinstance(bo_name, list): bo_name = bo_name[0]
            if not bo_name or bo_name == 'Unknown BO': return []
            
            clean_bo = re.sub(r'[^a-zA-Z0-9_]', '', bo_name).upper()
            table_name = f"TRIDATA.T_{clean_bo[:26]}"
            
            l_fields = node_data.get('LFldName', []) or node_data.get('PField', [])
            constants = node_data.get('ConstantValue', []) or node_data.get('Value', []) or node_data.get('RValue', [])
            op_code = node_data.get('Operator', '10')
            if isinstance(op_code, list) and op_code: op_code = op_code[0]
            
            if not l_fields or not constants: return []
                
            l_field = l_fields[0].upper()
            c_val = constants[0]
            
            sql = f"SELECT SPEC_ID FROM {table_name} WHERE 1=1"
            params = {'val0': c_val}
            
            if str(op_code) == '10': sql += f" AND {l_field} = :val0"
            elif str(op_code) == '11': sql += f" AND {l_field} != :val0"
            elif str(op_code) == '16': 
                sql += f" AND {l_field} LIKE :val0"
                params['val0'] = f"%{c_val}%"
            else: sql += f" AND {l_field} = :val0" 
                
            try:
                self.cursor.execute(sql, params)
                rows = self.cursor.fetchall()
                return [str(r[0]) for r in rows]
            except Exception:
                return []
                
        return []

    def fetch_live_record_data(self, expected_bo_name, spec_id):
        if not self.cursor or not spec_id: return None

        cache_key = (str(expected_bo_name), str(spec_id))
        if cache_key in self._record_payload_cache:
            return self._record_payload_cache[cache_key]

        payload = {}
        try:
            clean_spec_id = int(spec_id)
            true_bo_name = expected_bo_name
            
            try:
                sql = """
                    SELECT S.SPEC_NAME, T.NAME 
                    FROM TRIDATA.IBS_SPEC S 
                    LEFT JOIN TRIDATA.IBS_SPEC_TYPE T ON S.SPEC_TEMPLATE_ID = T.SPEC_TEMPLATE_ID 
                    WHERE S.SPEC_ID = :1
                """
                self.cursor.execute(sql, [clean_spec_id])
                spec_row = self.cursor.fetchone()
                if spec_row:
                    if spec_row[0]: payload['Record Name (IBS_SPEC)'] = spec_row[0]
                    if spec_row[1]: true_bo_name = spec_row[1]
            except Exception as e:
                payload['IBS_SPEC Error'] = str(e)

            payload['_True_BO_Name'] = true_bo_name

            if true_bo_name:
                clean_bo = re.sub(r'[^a-zA-Z0-9_]', '', true_bo_name).upper()
                table_name = f"TRIDATA.T_{clean_bo[:26]}"
                
                try:
                    self.cursor.execute(f"SELECT * FROM {table_name} WHERE SPEC_ID = :1", [clean_spec_id])
                    columns = [col[0].upper() for col in self.cursor.description]
                    t_row = self.cursor.fetchone()
                    
                    if t_row:
                        data = dict(zip(columns, t_row))
                        priority_fields = {'TRIRECORDIDSY': 'triRecordIdSY', 'TRISTATUSCL': 'triStatusCL', 'TRIIDTX': 'triIdTX', 'TRINAMETX': 'triNameTX'}
                        noisy_fields = ['TRILANGUAGELI', 'TRIMODIFIERBYTX', 'TRIPATHTX', 'SYS_GUIID', 'SYS_OBJECTID', 'SYS_PROJECTID', 'SPEC_ID']
                        
                        for db_col, readable_name in priority_fields.items():
                            if db_col in data and data[db_col] is not None and str(data[db_col]).strip() != '':
                                payload[readable_name] = data[db_col]
                        
                        extra_count = 0
                        for k, v in data.items():
                            if k not in priority_fields and k not in noisy_fields and not k.startswith('SYS_'):
                                if v is not None and str(v).strip() != '':
                                    if k.endswith('TX') or k.endswith('CL') or k.endswith('LI') or k.endswith('NU') or k.endswith('SY') or k.endswith('BL'):
                                        payload[k] = v
                                        extra_count += 1
                                        if extra_count >= 5: break
                except Exception as e:
                    payload['T_Table Error'] = f"Could not query {table_name}: {e}"
                                
        except Exception as e:
            payload['Database Error'] = str(e)

        result = payload if payload else None
        self._record_payload_cache[cache_key] = result
        return result

    def load_om_package(self, zip_source):
        """Load an OM Package from a filesystem path OR an in-memory file-like object.

        ``zipfile.ZipFile`` natively accepts both, so the CLI keeps passing paths while
        the Web UI passes ``io.BytesIO`` streams of the uploaded archive.
        """
        source_label = zip_source if isinstance(zip_source, str) else getattr(zip_source, 'name', '<in-memory upload>')
        print(f"Analyzing blueprint from OM Package: {source_label}...")
        try:
            with zipfile.ZipFile(zip_source, 'r') as z:
                xml_files = [f for f in z.namelist() if f.endswith('.xml') and not f.startswith('AllObjects') and not f.startswith('ObjectLabel')]
                if not xml_files:
                    print("FAILED: No valid workflow/logic blueprints found inside the OM package.")
                    return False
                
                workflow_xmls = []
                for f_name in xml_files:
                    with z.open(f_name) as f:
                        xml_string = f.read().decode('utf-8', errors='ignore')
                        # Detect root type on a namespace-stripped sample so prefixed
                        # roots (e.g. <ns:Workflow>) are still classified correctly.
                        head = self._strip_namespaces(xml_string[:500])
                        if '<Query>' in head:
                            self._parse_query_xml(xml_string)
                        elif '<Workflow>' in head:
                            workflow_xmls.append((f_name, xml_string))

                if not workflow_xmls:
                    print("FAILED: No valid Workflow logic blueprints found.")
                    return False

                for w_name, w_xml in workflow_xmls:
                    print(f"Targeting workflow logic file: {w_name}")
                    self._build_dynamic_graph(w_xml)
                    
                return True
        except FileNotFoundError:
            print(f"CRITICAL: OM Package '{source_label}' not found. Please check the path.")
            return False
        except zipfile.BadZipFile:
            print(f"CRITICAL: '{source_label}' is corrupt or not a valid zip archive.")
            return False

    def load_workflow_xml_file(self, file_path):
        """Load a bare workflow (or query) XML file that is not inside an OM Package."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                xml_string = f.read()
        except (FileNotFoundError, IsADirectoryError):
            print(f"CRITICAL: Workflow XML file '{file_path}' not found.")
            return False

        return self.load_workflow_xml_string(xml_string, source_label=file_path)

    def load_workflow_xml_string(self, xml_string, source_label='<in-memory upload>'):
        """Load a bare workflow (or query) XML payload already held in memory."""
        head = self._strip_namespaces(xml_string[:500])
        if '<Query>' in head:
            self._parse_query_xml(xml_string)
            print(f"SUCCESS: Parsed query XML from '{source_label}'.")
            return True
        if '<Workflow>' in head:
            print(f"Analyzing blueprint from raw XML file: {source_label}...")
            return self._build_dynamic_graph(xml_string)

        print(f"FAILED: '{source_label}' does not look like a TRIRIGA Workflow or Query XML export.")
        return False

    def _parse_query_xml(self, xml_payload):
        try:
            clean_xml = self._strip_namespaces(xml_payload)
            root = ET.fromstring(clean_xml)
            name_elem = root.find('.//Header/Name')
            if name_elem is None or not name_elem.text: return
            
            query_name = name_elem.text.strip()
            query_data = {'Columns': [], 'Filters': [], 'Module': 'Unknown Module', 'BO': 'Unknown BO'}
            
            mod_elem = root.find('.//Header/Module')
            if mod_elem is not None and mod_elem.text: query_data['Module'] = mod_elem.text.strip()
                
            bo_elem = root.find('.//Header/BO')
            if bo_elem is not None and bo_elem.text: query_data['BO'] = bo_elem.text.strip()
            
            for col in root.findall('.//Columns/Column'):
                c_type = col.get('Type')
                sec = col.find('SecName')
                fld = col.find('FldName')
                fval = col.find('FiltVAl')
                
                sec_text = sec.text.strip() if sec is not None and sec.text else ""
                fld_text = fld.text.strip() if fld is not None and fld.text else ""
                val_text = fval.text.strip() if fval is not None and fval.text else ""
                
                if c_type == '1': 
                    query_data['Columns'].append(f"{sec_text}::{fld_text}")
                elif c_type == '5': 
                    filt_type = col.get('FiltType', 'Unknown')
                    op_map = {'10': 'Equals', '11': 'Does Not Equal', '16': 'Contains'}
                    op_str = op_map.get(str(filt_type), f"Operator {filt_type}")
                    query_data['Filters'].append({'Field': f"{sec_text}::{fld_text}", 'Value': val_text, 'Operator': op_str})
                    
            self.queries[query_name] = query_data
        except ET.ParseError:
            pass

    def _build_dynamic_graph(self, xml_payload):
        try:
            clean_xml = self._strip_namespaces(xml_payload)
            root = ET.fromstring(clean_xml)
            
            header = root.find('.//Header')
            wf_name = "Unknown Workflow"
            if header is not None:
                def header_text(tag, default=""):
                    elem = header.find(tag)
                    return elem.text.strip() if elem is not None and elem.text and elem.text.strip() else default

                wf_name = header_text('Name', "Unknown Workflow")

                if wf_name not in self.loaded_workflow_names and wf_name != "Unknown Workflow":
                    self.loaded_workflow_names.append(wf_name)

                self.workflow_metadata[wf_name] = {
                    'Name': wf_name,
                    'Description': header_text('Description', "No description provided."),
                    'Module': header_text('Module'),
                    'BO': header_text('BO'),
                    'EventName': header_text('EventName'),
                    'ObjectLabelName': header_text('ObjectLabelName'),
                    'UpdatedBy': header_text('UpdatedBy'),
                }
            
            self.graphs[wf_name] = nx.DiGraph()
            
            elements = root.findall('.//Task') + root.findall('.//WorkflowTask') + root.findall('.//step')
            
            array_tags = [
                'Expression', 'PField', 'PModule', 'PBO', 'PSection', 
                'Field', 'TrgtFld', 'SrcFld', 'LFldName', 'RFldName', 
                'RValue', 'Value', 'ConstantValue', 'Operator',
                'Action', 'QueryName', 'AssociationName', 'AssocName', 
                'VariableName', 'ChildModule', 'ChildBO', 'RefObject', 'RefModule',
                'LTask', 'RTask', 'LTaskId', 'RTaskId', 'FilterBo', 'TargetAssociation'
            ]

            for el in elements:
                if el.tag == 'WFStep': continue
                
                node_id = el.get('Id', el.get('id', 'Unknown_ID'))
                
                if self.graphs[wf_name].has_node(node_id):
                    node_data = self.graphs[wf_name].nodes[node_id].copy()
                else:
                    node_data = {}
                
                label_element = el.find('TaskLabel')
                t_type = el.get('Type', el.get('type', 'Generic'))
                
                if label_element is not None and label_element.text and label_element.text.strip():
                    node_data['name'] = label_element.text.strip()
                else:
                    if str(t_type) == '9':
                        node_data['name'] = 'End'
                    elif 'name' not in node_data:
                        node_data['name'] = f"Unnamed Component ({node_id})"

                def traverse(element):
                    if element.tag == 'TaskRef':
                        u_type = element.get('UseType')
                        r_id = element.get('RefTaskId')
                        if u_type == '1' and r_id and r_id not in ['-1', '0', '']:
                            node_data.setdefault('FromTask', []).append(r_id)
                        elif u_type == '2' and r_id and r_id not in ['-1', '0', '']:
                            node_data.setdefault('FilterTask', []).append(r_id)

                    if element.text and element.text.strip() and element.tag not in ['TaskLabel']:
                        tag, val = element.tag, element.text.strip()
                        if tag in array_tags:
                            if tag not in node_data: node_data[tag] = []
                            if val not in node_data[tag]: node_data[tag].append(val)
                        elif tag in node_data and tag not in array_tags:
                            if isinstance(node_data[tag], list):
                                if val not in node_data[tag]: node_data[tag].append(val)
                            elif node_data[tag] != val: node_data[tag] = [node_data[tag], val]
                        else: 
                            node_data[tag] = val
                            
                    for attr, val in element.attrib.items():
                        if attr not in node_data: 
                            node_data[attr] = val
                            
                    for child in element: traverse(child)
                
                traverse(el)
                
                if 'GUIMappings' not in node_data: node_data['GUIMappings'] = []
                    
                for gm in el.findall('.//GUIMapping'):
                    gm_data = {'PropType': gm.get('PropType', '')}
                    for tag in ['Tab', 'Section', 'Field', 'PropVal']:
                        child = gm.find(tag)
                        if child is not None and child.text: gm_data[tag] = child.text.strip()
                    if gm_data not in node_data['GUIMappings']: node_data['GUIMappings'].append(gm_data)

                # Structured ObjMapping extraction: each <ObjMapping> is an ordered, self-contained
                # data-mapping record. We preserve document order and per-record field grouping so that
                # a Target field is never index-zipped against an unrelated Source field downstream.
                if 'ObjMappingRecords' not in node_data: node_data['ObjMappingRecords'] = []
                obj_map_tags = [
                    'TrgtModule', 'TrgtBo', 'TrgtTab', 'TrgtSec', 'TrgtFld',
                    'SrcModule', 'SrcBo', 'SrcTab', 'SrcSec', 'SrcFld',
                    'FldVal', 'SrcFldVal'
                ]
                for om in el.findall('.//ObjMapping'):
                    rec = {'Type': om.get('Type', '')}
                    for tag in obj_map_tags:
                        child = om.find(tag)
                        if child is not None and child.text and child.text.strip():
                            rec[tag] = child.text.strip()
                    # Keep only mappings that actually carry a target or a value; skip empty scaffolding.
                    if rec.get('TrgtFld') or rec.get('FldVal') or rec.get('SrcFld'):
                        if rec not in node_data['ObjMappingRecords']:
                            node_data['ObjMappingRecords'].append(rec)

                # Structured TaskRef extraction. TaskRef context (Ref* fields) describes *where a
                # task pulls its records from*, which is a different scope than the task's own
                # Condition/Param evaluation fields. Capturing them as discrete records keeps that
                # reference context from being conflated with the task's evaluation metadata.
                if 'TaskRefRecords' not in node_data: node_data['TaskRefRecords'] = []
                task_ref_tags = ['RefModule', 'RefObject', 'RefSec', 'RefField', 'RefAssoc', 'RefRecordMod', 'RefRecordBO', 'RefRecord']
                for tr in el.findall('.//TaskRef'):
                    ref_rec = {
                        'UseType': tr.get('UseType', ''),
                        'RefTaskId': tr.get('RefTaskId', ''),
                        'CtxType': tr.get('CtxType', ''),
                    }
                    for tag in task_ref_tags:
                        child = tr.find(tag)
                        if child is not None and child.text and child.text.strip():
                            ref_rec[tag] = child.text.strip()
                    if len(ref_rec) > 3:
                        if ref_rec not in node_data['TaskRefRecords']:
                            node_data['TaskRefRecords'].append(ref_rec)

                new_type = node_data.get('Type', node_data.get('type'))
                if new_type: node_data['type'] = new_type
                elif 'type' not in node_data: node_data['type'] = 'Generic'
                    
                self.graphs[wf_name].add_node(node_id, **node_data)
                
            wfsteps = root.findall('.//WFStep')
            for step in wfsteps:
                step_id = step.get('Id')
                par_id = step.get('ParId')
                step_type = step.get('Type')
                
                if step_id and not self.graphs[wf_name].has_node(step_id):
                    name = "End" if str(step_type) == '9' else f"Unnamed Component ({step_id})"
                    self.graphs[wf_name].add_node(step_id, name=name, type=step_type or 'Generic')
                if par_id and par_id not in ["-1", ""] and not self.graphs[wf_name].has_node(par_id):
                    self.graphs[wf_name].add_node(par_id, name=f"Unnamed Component ({par_id})", type='Generic')
                    
                if step_id and par_id and par_id not in ["-1", ""]:
                    self.graphs[wf_name].add_edge(par_id, step_id)

            print(f"SUCCESS: Mapped {self.graphs[wf_name].number_of_nodes()} components for '{wf_name}'.\n")
            return True
        except ET.ParseError as e:
            print(f"FAILED: XML blueprint is malformed. Error: {e}")
            return False

    def _live_database_check(self, query, parameters):
        if not self.cursor: return False
        cache_key = (query, tuple(parameters))
        if cache_key in self._validation_cache:
            return self._validation_cache[cache_key]
        try:
            self.cursor.execute(query, parameters)
            result = self.cursor.fetchone() is not None
        except Exception:
            result = False
        self._validation_cache[cache_key] = result
        return result

    def analyze_health(self):
        print("--- Initiating Universal Hybrid Diagnostic Trace ---\n")
        if not self.graphs:
            print("Engine halted: No workflows available to analyze.")
            return

        warnings_found = 0

        def validate_live_data(wf_name, task_name, key_names, query, error_type, item_type):
            nonlocal warnings_found
            for key in key_names:
                items = data.get(key)
                if items:
                    item_list = items if isinstance(items, list) else [items]
                    for item in item_list:
                        if item in ['System', 'Workflow', 'Any', 'Location']: continue
                        if not self._live_database_check(query, [item]):
                            print(f"[{wf_name}][{error_type}] Task '{task_name}' references {item_type} '{item}', but it DOES NOT EXIST in the live environment.")
                            warnings_found += 1

        for wf_name, graph in self.graphs.items():
            for node, data in graph.nodes(data=True):
                node_name = data.get('name', 'Unknown')
                node_type = data.get('type', 'Generic')
                
                if graph.in_degree(node) == 0 and str(node_type) not in ['1', 'Trigger', 'Start']:
                    print(f"[{wf_name}][STRUCTURAL NOTE] Root or Orphan Logic: '{node_name}' (Type Code: {node_type}) has no incoming transitions.")

                validate_live_data(
                    wf_name, node_name, ['Module', 'ModuleName', 'PModule', 'ChildModule', 'RefModule'], 
                    "SELECT module_id FROM TRIDATA.IBS_MODULE WHERE UPPER(TRIM(module_name)) = UPPER(TRIM(:1)) FETCH FIRST 1 ROWS ONLY", 
                    "LIVE DB ERROR", "Module"
                )
                
                validate_live_data(
                    wf_name, node_name, ['BO', 'BoName', 'PBO', 'ChildBO', 'RefObject'], 
                    "SELECT spec_template_id FROM TRIDATA.IBS_SPEC_TYPE WHERE UPPER(TRIM(name)) = UPPER(TRIM(:1)) FETCH FIRST 1 ROWS ONLY", 
                    "LIVE DB ERROR", "Business Object (BO)"
                )

                validate_live_data(
                    wf_name, node_name, ['AssociationName', 'Association', 'AssocName'], 
                    "SELECT 1 FROM TRIDATA.IBS_SPEC_ASSIGNMENTS WHERE UPPER(TRIM(ass_type)) = UPPER(TRIM(:1)) FETCH FIRST 1 ROWS ONLY", 
                    "LIVE DB ERROR", "Association"
                )

        if warnings_found == 0:
            print("\n[HEALTHY] All structural paths are intact, and all cross-referenced database dependencies are valid in the live system.")
        else:
            print(f"\nDiagnostics Complete: {warnings_found} critical issues identified requiring remediation.")

    def shutdown(self):
        if self.cursor: self.cursor.close()
        if self.db_conn: self.db_conn.close()
        print("\nEngine shutting down. Live connections closed.")