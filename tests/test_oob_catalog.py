"""Tests for tririga_modules_bos.json catalog loader + generator API."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from om_gen.oob_catalog import (
    catalog_payload,
    clear_cache,
    is_known_bo,
    is_known_module,
    list_bos,
    list_modules,
    load_modules_bos,
)


class TestOobCatalog(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_load_full_json(self):
        data = load_modules_bos()
        self.assertGreaterEqual(len(data), 90)
        self.assertIn('Location', data)
        self.assertIn('triContract', data)
        bos = data['Location']
        self.assertIn('triBuilding', bos)
        self.assertIn('triLand', bos)
        self.assertGreaterEqual(len(data['triContract']), 5)

    def test_helpers(self):
        mods = list_modules()
        self.assertEqual(mods, sorted(mods))
        self.assertTrue(is_known_module('Location'))
        self.assertTrue(is_known_bo('Location', 'triBuilding'))
        self.assertFalse(is_known_bo('Location', 'NotARealBOXYZ'))
        self.assertIn('triBuilding', list_bos('Location'))

    def test_catalog_payload_shape(self):
        payload = catalog_payload()
        self.assertIn('modules', payload)
        self.assertIsInstance(payload['modules'], dict)
        self.assertIn('Location', payload['modules'])


class TestCatalogAPI(unittest.TestCase):
    def test_catalog_payload_via_helper(self):
        # Mirror what GET /api/generator/catalog returns
        from om_gen.oob_catalog import catalog_payload as cp
        data = cp()
        self.assertGreaterEqual(len(data['modules']), 90)
        self.assertIn('triBuilding', data['modules']['Location'])


if __name__ == '__main__':
    unittest.main()
