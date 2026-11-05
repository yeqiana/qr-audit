"""Explicit, opt-in recognition fallbacks that preserve baseline strategy order.

A fallback result is *observed offline coverage*, not verified QR correctness.
"""
from collections import defaultdict
from copy import deepcopy


def compose_registry(original, boost, with_wechat):
    """Append experimental B strategies after every existing native/reference ID."""
    result = deepcopy(original)
    existing = {row["strategy_id"] for row in result["strategies"]}
    added = []
    for row in boost["strategies"]:
        sid = row["strategy_id"]
        if sid in existing:
            raise ValueError("FALLBACK_STRATEGY_COLLISION: " + sid)
        if not sid.startswith("B"):
            raise ValueError("FALLBACK_INVALID_STRATEGY: " + sid)
        existing.add(sid)
        added.append(deepcopy(row))
    if not added or "B01" not in existing:
        raise ValueError("FALLBACK_REQUIRES_B01")
    if with_wechat:
        if "W01" in existing:
            raise ValueError("FALLBACK_STRATEGY_COLLISION: W01")
        added.append({
            "strategy_id": "W01",
            "order": len(result["strategies"]) + len(added) + 1,
            "name_zh": "微信模型原图兜底",
            "family": "wechat_last_resort",
            "parameters": {"operation": "identity"},
            "implementation_status": "EXPERIMENT_ONLY",
            "notes": "Last resort, WeChatQRCode on unmodified input. Not mobile WeChat app.",
        })
    result["strategies"].extend(added)
    result["fallback_composition"] = {
        "version": "1",
        "base_strategy_ids": [x["strategy_id"] for x in original["strategies"]],
        "boost_strategy_ids": [x["strategy_id"] for x in boost["strategies"]],
        "wechat_strategy_id": "W01" if with_wechat else None,
    }
    return result


def decoder_filters(base_strategy_ids, boost_strategy_ids, original_decoder_ids,
                    effective_decoder_ids, with_wechat):
    """Keep source-file/native adapters away from experimental pixel variants."""
    base, boost, old = set(base_strategy_ids), set(boost_strategy_ids), set(original_decoder_ids)
    allowed = {}
    for did in effective_decoder_ids:
        if did == "wechat" and with_wechat:
            allowed[did] = {"W01"}
        elif did in ("opencv", "zxingcpp"):
            # Original decoders retain all baseline calls; injected ones only
            # participate in the opt-in experimental B strategies.
            allowed[did] = (base | boost) if did in old else boost.copy()
        else:
            # Native/local adapters may require a source_file path and must
            # never receive a B-variant pixel array.
            allowed[did] = base.copy()
    return allowed


def summarize(attempts, manifest):
    """Observed incremental coverage *inside this one combined run*."""
    composition = manifest.get("fallback_composition")
    if not composition:
        return None
    base = set(composition["base_strategy_ids"])
    boost = set(composition["boost_strategy_ids"])
    extras = boost | ({"W01"} if composition["wechat_strategy_id"] else set())
    base_success = set()
    fallback_success = set()
    strategy_rescues = defaultdict(set)
    for row in attempts:
        if row.get("status") != "DECODED":
            continue
        image_id = row["image_id"]
        sid = row["strategy_id"]
        if sid in base:
            base_success.add(image_id)
        elif sid in extras:
            fallback_success.add(image_id)
            strategy_rescues[sid].add(image_id)
    newly_rescued = fallback_success - base_success
    pair_members = defaultdict(set)
    for row in manifest["images"]:
        if row.get("pair_status") == "PAIRED" and row.get("pair_id") is not None:
            pair_members[row["pair_id"]].add(row["image_id"])
    old_pairs = {pid for pid, members in pair_members.items()
                 if any(x in base_success for x in members)}
    union_success = base_success | fallback_success
    union_pairs = {pid for pid, members in pair_members.items()
                   if any(x in union_success for x in members)}
    return {
        "status": "OBSERVED_UNVERIFIED",
        "baseline_success_images": len(base_success),
        "fallback_success_images": len(fallback_success),
        "newly_rescued_images": len(newly_rescued),
        "baseline_success_pairs": len(old_pairs),
        "newly_rescued_pairs": len(union_pairs - old_pairs),
        "final_success_images": len(union_success),
        "final_success_pairs": len(union_pairs),
        "rescue_by_strategy": {s: len(ids - base_success) for s, ids in sorted(strategy_rescues.items())},
        "warning": ("Counts denote offline DECODED coverage, not validated correctness. "
                    "Independent truth and historical zero-regression gate are required."),
    }
