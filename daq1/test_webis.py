"""Offline tests for webis.py using responses captured from the testbed (2026-11-20).

Run:  uv run pytest
"""

import httpx

import webis

# Trimmed copy of the real RunCtrl.RootController response from partition 'mytest'
ROOT_CONTROLLER = [
    "RunCtrl.RootController", "RCStateInfo", "20/11/26 10:42:47.605131",
    {"name": "state", "descr": "Current state of the controller", "type": "string", "range": "", "value": "INITIAL"},
    {"name": "busy", "descr": "...", "type": "bool", "range": "", "value": False},
    {"name": "fault", "descr": "...", "type": "bool", "range": "", "value": False},
    {"name": "errorReasons", "descr": "...", "type": "string", "range": "", "value": []},
    {"name": "lastTransitionName", "descr": "...", "type": "string", "range": "", "value": "INITIALIZE"},
]
NOT_FOUND = {"error": "invalid_object", "error_description": "No such object: RunCtrl.DoesNotExist"}


def fake_get(status, body):
    def _get(url, params=None, timeout=None):
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))
    return _get


def test_url():
    assert webis.object_url("mytest", "RunCtrl", "RootController") == \
        "http://127.0.0.1:8080/info/current/mytest/is/RunCtrl/RunCtrl.RootController"
    # dotted object names (from ATLAS.js) must survive
    assert webis.object_url("ATLAS", "DF", "TopMIG-IS:HLT.info").endswith("/DF/DF.TopMIG-IS:HLT.info")


def test_ok(monkeypatch):
    monkeypatch.setattr(webis.httpx, 'get', fake_get(200, ROOT_CONTROLLER))
    o = webis.get_object("mytest", "RunCtrl", "RootController")
    assert o["type"] == "RCStateInfo"
    assert o["updated"] == "20/11/26 10:42:47.605131"
    assert o["attributes"]["state"] == "INITIAL"
    assert o["attributes"]["fault"] is False


def test_missing_object(monkeypatch):
    monkeypatch.setattr(webis.httpx, 'get', fake_get(404, NOT_FOUND))
    try:
        webis.get_object("mytest", "RunCtrl", "DoesNotExist")
    except webis.WebisError as e:
        assert e.code == "invalid_object"
        assert "No such object" in e.description
    else:
        raise AssertionError("expected WebisError")


def test_unreachable(monkeypatch):
    def boom(url, params=None, timeout=None):
        raise httpx.ConnectError("Connection refused")
    monkeypatch.setattr(webis.httpx, 'get', boom)
    try:
        webis.get_object("mytest", "RunCtrl", "RootController")
    except webis.WebisError as e:
        assert e.code == "unreachable"
    else:
        raise AssertionError("expected WebisError")

