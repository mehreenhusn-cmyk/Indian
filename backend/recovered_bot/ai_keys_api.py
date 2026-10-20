"""
ai_keys_api.py - the 4 AI key slots in one place: paste a key, the backend detects whose key it is and which model to use.

  status()            -> the 4 slots with provider, model, state (ready / out of quota / error) and call numbers
  add(key, slot=None) -> detect + save into the chosen slot (or the first empty one)
  test(slot)          -> one tiny call to the slot's model, plain-words answer
  clear(slot)         -> empty a slot

The old settings fields (ai_api_key, ai2_api_key ...) stay the single source of truth, so ai_vision.py, the chat assistant
and the backup/restore logic keep working unchanged. Never raises.
"""
import time

from . import ai_keyid, settings_store

SLOTS = (("main", "ai", "Main key"), ("backup", "ai2", "Backup key 1"), ("backup2", "ai3", "Backup key 2"), ("backup3", "ai4", "Backup key 3"))
_PFX = {s: p for s, p, _ in SLOTS}


def _key_of(pfx):
    return str(settings_store.get(f"{pfx}_api_key", "") or "").strip()


def _slot_dict(vision):
    return {sl["slot"]: sl for sl in (vision._slots() if vision else [])}


def status():
    from . import ai_vision as v
    live = _slot_dict(v)
    mon = {x["slot"]: x for x in (v.monitor().get("slots") or [])}
    out = []
    for slot, pfx, label in SLOTS:
        key = _key_of(pfx)
        row = {"slot": slot, "label": label, "filled": bool(key), "masked": ai_keyid.mask(key)}
        if key:
            sl = live.get(slot) or {}
            prov = sl.get("provider") or ""
            m = mon.get(slot) or {}
            state = "paused" if m.get("state") == "paused" else "ready"
            err = str(v._slot_err.get(slot, "") or "")
            if err and state == "ready":
                state = "error"
            row.update({"provider": prov, "provider_name": ai_keyid.NAMES.get(prov, prov), "model": (v._slot_models(sl) or [""])[0] if sl else "",
                        "state": state, "paused_until": m.get("paused_until") or 0, "calls": m.get("calls", 0), "ok": m.get("ok", 0),
                        "quota": m.get("quota", 0), "errors": m.get("errors", 0), "avg_s": m.get("avg_s"), "last_error": err[:200]})
        out.append(row)
    return {"slots": out, "now": int(time.time())}


def _unpause(slot):
    try:
        from . import ai_vision as v
        for k in [k for k in list(v._pause) if k.startswith(slot + ":")]:
            v._pause.pop(k, None)
        v._slot_err.pop(slot, None)
        v._stat["error"] = ""
    except Exception:
        pass


def _save(slot, key, prov, model):
    pfx = _PFX[slot]
    settings_store.update(**{f"{pfx}_api_key": key, f"{pfx}_provider": prov, f"{pfx}_model": "",
                             f"{pfx}_auto_model": model or "", f"{pfx}_auto_prov": prov})
    _unpause(slot)


def add(key, slot=None):
    key = str(key or "").strip().replace(" ", "").replace("\n", "")
    if len(key) < 12:
        return {"ok": False, "message": "That is too short to be a key. Copy the whole key and paste again."}
    for s, pfx, label in SLOTS:
        if _key_of(pfx) == key:
            return {"ok": False, "message": f"This key is already saved as '{label}'."}
    if slot and slot not in _PFX:
        return {"ok": False, "message": "Unknown slot."}
    if not slot:
        for s, pfx, label in SLOTS:
            if not _key_of(pfx):
                slot = s
                break
    if not slot:
        return {"ok": False, "need_slot": True, "message": "All 4 slots are full. Choose which key to replace."}
    res = ai_keyid.inspect(key, force=True)
    label = dict((s, l) for s, _, l in SLOTS)[slot]
    if res["ok"]:
        _save(slot, key, res["provider"], res["model"])
        return {"ok": True, "slot": slot, "label": label, "provider": res["provider"], "provider_name": res["provider_name"],
                "model": res["model"], "message": f"Saved as '{label}': {res['provider_name']}, model {res['model']}."}
    g, sure = ai_keyid.guess(key)
    if res["state"] == "network" and g and sure:
        _save(slot, key, g, "")
        return {"ok": True, "slot": slot, "label": label, "provider": g, "provider_name": ai_keyid.NAMES.get(g, g), "model": "",
                "message": f"Saved as '{label}' ({ai_keyid.NAMES.get(g, g)}), but I could not check it now (no internet). Press Test later."}
    return {"ok": False, "slot": slot, "message": res["message"]}


def detect(slot):
    """Check the saved key again and refresh its model (use after a '404 model retired' message)."""
    if slot not in _PFX:
        return {"ok": False, "message": "Unknown slot."}
    key = _key_of(_PFX[slot])
    if not key:
        return {"ok": False, "message": "This slot is empty."}
    res = ai_keyid.inspect(key, force=True)
    if res["ok"]:
        _save(slot, key, res["provider"], res["model"])
    return {"ok": res["ok"], "slot": slot, "provider": res["provider"], "model": res["model"], "message": res["message"]}


def test(slot):
    if slot not in _PFX:
        return {"state": "error", "message": "Unknown slot."}
    from . import ai_vision as v
    sl = _slot_dict(v).get(slot)
    if not sl:
        return {"state": "error", "message": "This slot is empty."}
    model = (v._slot_models(sl) or [""])[0]
    r = ai_keyid.test_call(sl["provider"], sl["key"], model)
    r["provider"] = sl["provider"]
    r["model"] = model
    if r["state"] == "ready":
        _unpause(slot)
    elif r["state"] == "bad_model":
        d = detect(slot)
        if d.get("ok") and d.get("model") and d["model"] != model:
            r2 = ai_keyid.test_call(sl["provider"], sl["key"], d["model"])
            r2.update({"provider": sl["provider"], "model": d["model"], "message": "Old model was retired. Switched to " + d["model"] + ". " + r2["message"]})
            return r2
    return r


def clear(slot):
    if slot not in _PFX:
        return {"ok": False, "message": "Unknown slot."}
    pfx = _PFX[slot]
    settings_store.update(**{f"{pfx}_api_key": "", f"{pfx}_model": "", f"{pfx}_auto_model": "", f"{pfx}_auto_prov": ""})
    _unpause(slot)
    return {"ok": True, "message": "Key removed."}
