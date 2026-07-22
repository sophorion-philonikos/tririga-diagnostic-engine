# om_gen — ObjectLabel fixtures and TRIRIGA import

## Fixtures

`om_gen/fixtures/` ships two ObjectLabel XML files copied from
`Land_OnChange_RPIM_Status_Ind/`:

| File | Label |
|------|-------|
| `ObjectLabel_b037d8e4859a408ee21b48cc5787f6f3d1fa81c5.xml` | Root 0.0 |
| `ObjectLabel_cfb478ea4b3c19a2077f1d82f3fb196c5534c0db.xml` | In Progress 0.0 |

Generated workflows default to **In Progress 0.0**.

## If ObjectLabel import fails

1. In your TRIRIGA env, export an OM package that includes the ObjectLabels you use.
2. Copy the `ObjectLabel_*.xml` files into `om_gen/fixtures/`.
3. Update filenames in `om_gen/__init__.py` → `OBJECT_LABEL_FIXTURES`.
4. Rebuild the zip.

## Import checklist

1. `python3 -m om_gen build --recipe path.json --out /tmp/gen.zip` (or use the Generator web page).
2. Confirm members are flat: `unzip -l /tmp/gen.zip` (no folders).
3. Import via TRIRIGA Object Migration.
4. Query/Call tasks reference objects that must already exist in the target environment
   (Type-4 Query payloads are not packaged by om_gen).
