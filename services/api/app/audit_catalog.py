import argparse

from app.db import SessionLocal
from app.services.card_audit import CardAuditReport, run_card_audit


def print_report(report: CardAuditReport) -> None:
    data = report.to_dict()
    summary = data["summary"]

    print(f"total_cards: {summary['total_cards']}")
    print(f"total_issues: {summary['total_issues']}")
    print(f"critical_issues: {summary['critical_issues']}")
    print(f"warning_issues: {summary['warning_issues']}")

    counts: dict[str, int] = {}
    for issue in data["issues"]:
        counts[issue["issue_type"]] = counts.get(issue["issue_type"], 0) + 1

    print()
    print("issues by type:")
    for issue_type, count in sorted(counts.items()):
        print(f"  {issue_type}: {count}")

    print()
    print("issue details:")
    for issue in data["issues"]:
        print(f"  [{issue['severity']}] {issue['issue_type']}: {issue['message']}")
        print(f"    card_ids: {issue['card_ids']}")
        print(f"    suggested_action: {issue['suggested_action']}")


def main() -> None:
    argparse.ArgumentParser(
        description="Audit the card catalog for data-quality issues."
    ).parse_args()

    try:
        db = SessionLocal()
        try:
            report = run_card_audit(db)
        finally:
            db.close()
    except Exception as exc:
        print(f"error: audit failed: {exc}")
        raise SystemExit(1)

    print_report(report)


if __name__ == "__main__":
    main()
