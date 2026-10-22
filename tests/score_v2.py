"""Score Lane on the 53 v2 emails via POST /api/classify (bearer auth).

Usage: python tests/score_v2.py --direct
       python tests/score_v2.py [base_url] [token] [out.json]
"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from new_emails_v2 import EMAILS

CUR = [("R$", "BRL"), ("MXN", "MXN"), ("US$", "USD"), ("USD", "USD"), ("EUR", "EUR"), ("GBP", "GBP"),
       ("$", "USD"), ("€", "EUR"), ("£", "GBP"), ("¥", "JPY"), ("円", "JPY"), ("euro", "EUR"), ("quid", "GBP")]

def norm_money(v):
    if v in (None, "?"): return v
    s = str(v)
    cur = next((code for sym, code in CUR if sym.lower() in s.lower()), "USD")
    m = re.search(r"\d[\d,\.]*", s.replace(" ", ""))
    if not m: return (cur, None)
    num = m.group(0).rstrip(".,")
    # thousands separators: treat both , and . followed by 3 digits as grouping
    num = re.sub(r"[.,](?=\d{3}(\D|$))", "", num).replace(",", ".")
    try: n = int(float(num))
    except ValueError: n = None
    return (cur, n)

def same(a, b):
    if a is None or b is None: return a is None and b is None
    return str(a).strip().casefold() == str(b).strip().casefold()

def get_classifier(argv):
    if "--direct" in argv:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app.llm import classify_email
        return lambda e: classify_email(dict(e)).as_dict()
    import httpx
    args = [a for a in argv[1:] if not a.startswith("--")]
    base = args[0] if args else "http://127.0.0.1:8741/api"
    token = args[1] if len(args) > 1 else "lane-demo-token"
    c = httpx.Client(timeout=120, headers={"Authorization": f"Bearer {token}"})
    def run(e):
        r = c.post(f"{base}/classify", json={k: e[k] for k in ("subject", "body", "from_name", "from_email")})
        r.raise_for_status(); return r.json()
    return run

def main(argv):
    clf = get_classifier(argv)
    args = [a for a in argv[1:] if not a.startswith("--")]
    out = args[2] if len(args) > 2 else "new_emails_v2_results.json"
    rows = []
    for e in EMAILS:
        b = clf(e)
        cat = b["category"]
        row = dict(id=e["id"], expected=sorted(e["label"]), got=cat, conf=b["confidence"],
                   cat_ok=cat in e["label"], must_flag=e.get("must_flag", False),
                   flagged=cat == "suspicious", risk_flags=b.get("risk_flags"),
                   secondary=b.get("secondary_categories"), intent=b["intent"], draft=b["draft_reply"][:140])
        for f in ("name", "company"):
            exp = e[f]; row[f] = (exp, b[f], None if exp == "?" else same(b[f], exp))
        exp = e["budget"]; got = b["budget"]
        row["budget"] = (exp, got, None if exp == "?" else (norm_money(got) == norm_money(exp)))
        rows.append(row)
        print(f'{"OK " if row["cat_ok"] else "BAD"} {e["id"]} exp={"/".join(row["expected"]):17s} got={cat:10s} '
              f'n={"✓" if row["name"][2] else "·" if row["name"][2] is None else "✗"}({b["name"]}) '
              f'c={"✓" if row["company"][2] else "·" if row["company"][2] is None else "✗"}({b["company"]}) '
              f'b={"✓" if row["budget"][2] else "·" if row["budget"][2] is None else "✗"}({got} vs {exp}) flags={b.get("risk_flags")}')
    json.dump(rows, open(out, "w"), indent=1, ensure_ascii=False)
    n = len(rows)
    print(f"\nclassification {sum(r['cat_ok'] for r in rows)}/{n}")
    groups = {}
    for e, r in zip(EMAILS, rows):
        g = "phish/fraud/injection" if e.get("must_flag") else ("mixed" if len(e["label"]) > 1 and "spam" not in e["label"] else sorted(e["label"])[0])
        groups.setdefault(g, [0, 0]); groups[g][1] += 1; groups[g][0] += r["cat_ok"]
    for g, (a, t) in sorted(groups.items()): print(f"  {g:22s} {a}/{t}")
    mf = [r for r in rows if r["must_flag"]]
    print(f"phishing/fraud/injection flagged suspicious: {sum(r['flagged'] for r in mf)}/{len(mf)}")
    legit = [r for r in rows if not (set(r["expected"]) & {"spam", "suspicious"})]
    print(f"legit mail wrongly flagged suspicious: {[r['id'] for r in legit if r['flagged']]} ({sum(r['flagged'] for r in legit)}/{len(legit)})")
    tot_hit = tot_n = 0
    for f in ("name", "company", "budget"):
        pos = [r for r in rows if r[f][0] not in (None, "?")]
        neg = [r for r in rows if r[f][0] is None]
        hit = sum(bool(r[f][2]) for r in pos); inv = sum(r[f][1] is not None for r in neg)
        tot_hit += hit; tot_n += len(pos)
        print(f"{f:8s} correct when a value exists {hit}/{len(pos)} | invented when none exists {inv}/{len(neg)}")
    print(f"fields with a value (name+company+budget): {tot_hit}/{tot_n}")
    inv_all = sum(r[f][1] is not None for r in rows for f in ("name", "company", "budget") if r[f][0] is None)
    neg_all = sum(1 for r in rows for f in ("name", "company", "budget") if r[f][0] is None)
    print(f"invented values: {inv_all}/{neg_all}")
    print("non-leads that would go to the CRM:", [r["id"] for r in rows if (r["got"] == "lead" or "lead" in (r["secondary"] or [])) and "lead" not in r["expected"] and r["got"] not in ("spam", "suspicious")])
    print("leads missed:", [r["id"] for r in rows if "lead" in r["expected"] and r["got"] != "lead" and "lead" not in (r["secondary"] or [])])
    print("urgent missed:", [r["id"] for r in rows if r["expected"] == ["urgent"] and r["got"] != "urgent"])

if __name__ == "__main__":
    main(sys.argv)
