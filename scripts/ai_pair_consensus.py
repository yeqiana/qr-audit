"""Read-only cross-image pair hypothesis report; not QR decoding.

If one side decodes and its paired sibling does not, never mark the sibling
DECODED. Pairing does not prove equal underlying QR payload.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def _hash_ids(attempt):
    ids=set()
    if attempt.get("status")!="DECODED":
        return ids
    for item in attempt.get("payloads",[]):
        if isinstance(item,dict):
            identity=item.get("identity")
            if isinstance(identity,dict):
                algorithm=identity.get("algorithm")
                scope=identity.get("scope")
                value=identity.get("value")
                if algorithm=="sha256" and value:
                    ids.add((str(scope),str(value)))
    if not ids and attempt.get("payload_sha256"):
        ids.add((str(attempt.get("payload_hash_scope","")),str(attempt["payload_sha256"])))
    return ids


def audit_pairs(inventory, attempts):
    successes=defaultdict(set)
    for row in attempts:
        for identity in _hash_ids(row):
            successes[row.get("image_id")].add(identity)
    report=[]
    for group in inventory.get("groups",[]):
        for pair in group.get("pairs",[]):
            left=pair.get("left_file_ids",pair.get("left_ids",[]))
            right=pair.get("right_file_ids",pair.get("right_ids",[]))
            if len(left)!=1 or len(right)!=1:
                continue
            a,b=left[0],right[0]
            x,y=successes.get(a,set()),successes.get(b,set())
            if x and y:
                status="PAYLOAD_HASH_AGREEMENT" if x==y else "PAYLOAD_CONFLICT_REVIEW"
            elif x or y:
                status="INFERRED_FROM_PAIR_ONLY"
            else:
                status="NO_PAIR_INFORMATION"
            report.append({
                "group_id":group.get("group_id"),
                "pair_id":pair.get("pair_id"),"status":status,
                "decoded_left":bool(x),"decoded_right":bool(y),
                "source_image_ids":[z for z in (a,b) if successes.get(z)],
                "undecoded_image_ids":[z for z in (a,b) if not successes.get(z)],
                "payload_hashes":[{"scope":scope,"sha256":value}
                                  for scope,value in sorted(x|y)],
                "counts_as_newly_decoded":False,
            })
    status_counts=defaultdict(int)
    for entry in report:status_counts[entry["status"]]+=1
    return {
        "status":"HYPOTHESIS_ONLY",
        "pair_count":len(report),
        "by_status":dict(sorted(status_counts.items())),
        "pairs":report,
        "warning":("Paired-image identity does not prove equal QR data. "
                   "Do not combine inferred sibling payloads with true DECODED coverage."),
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description="审计配对图片的载荷一致性，不生成伪解码结果")
    parser.add_argument("--inventory",required=True)
    parser.add_argument("--attempts",required=True)
    parser.add_argument("--out",required=True)
    args=parser.parse_args(argv)
    inv=json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    attempts=[json.loads(x) for x in Path(args.attempts).read_text(
        encoding="utf-8").splitlines() if x.strip()]
    result=audit_pairs(inv,attempts)
    target=Path(args.out)
    with target.open("x",encoding="utf-8") as writer:
        json.dump(result,writer,ensure_ascii=False,indent=2)
    print(json.dumps({"status":result["status"],
                      "pair_count":result["pair_count"],
                      "by_status":result["by_status"]},ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
