import glob
import json
import collections

def analyze_outputs():
    outputs = glob.glob('outputs/L3A_CASE_*.json')
    
    primary_issues = collections.Counter()
    confidences = collections.Counter()
    evidence_counts = collections.Counter()
    refund_amounts = collections.Counter()
    case_statuses = collections.Counter()
    responsible_parties = collections.Counter()
    verdicts = collections.Counter()

    for file in outputs:
        with open(file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            assessment = data.get("assessment", {})
            primary_issues[assessment.get("primary_issue")] += 1
            conf = assessment.get("confidence")
            # bucket confidence
            if conf is not None:
                conf_bucket = round(conf, 2)
                confidences[conf_bucket] += 1
                
            case_statuses[assessment.get("case_status")] += 1
            
            evidence_refs = data.get("evidence_refs", [])
            evidence_counts[len(evidence_refs)] += 1
            
            fin = data.get("financial_resolution", {})
            refund = fin.get("recommended_refund_brl", 0)
            if refund > 0:
                refund_amounts["positive"] += 1
            else:
                refund_amounts["zero"] += 1
                
            rca = data.get("root_cause_analysis", {})
            parties = rca.get("responsible_parties", [])
            if not parties:
                responsible_parties["none"] += 1
            for p in parties:
                responsible_parties[p.get("party_type")] += 1
                
            claims = data.get("claim_assessments", [])
            for c in claims:
                verdicts[c.get("verdict")] += 1

    print("=== Thống kê 100 cases ===")
    print("\nPrimary Issues:")
    for k, v in primary_issues.most_common():
        print(f"  {k}: {v}")
        
    print("\nConfidence Buckets:")
    for k, v in confidences.most_common():
        print(f"  {k}: {v}")
        
    print("\nEvidence Refs Count Distribution:")
    for k, v in sorted(evidence_counts.items()):
        print(f"  {k} refs: {v} cases")
        
    print("\nRefund Amounts:")
    for k, v in refund_amounts.most_common():
        print(f"  {k}: {v}")
        
    print("\nCase Statuses:")
    for k, v in case_statuses.most_common():
        print(f"  {k}: {v}")
        
    print("\nResponsible Parties:")
    for k, v in responsible_parties.most_common():
        print(f"  {k}: {v}")
        
    print("\nClaim Verdicts:")
    for k, v in verdicts.most_common():
        print(f"  {k}: {v}")

if __name__ == '__main__':
    analyze_outputs()
