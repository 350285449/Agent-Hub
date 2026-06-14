from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class QualityScore:
    score: float
    tests_passed: int = 0
    tests_failed: int = 0
    user_accepted: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "score": round(max(0.0, min(1.0, self.score)), 4),
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "user_accepted": self.user_accepted,
        }


def score_quality(*, success: bool, tests_passed: int = 0, tests_failed: int = 0, user_accepted: bool | None = None) -> QualityScore:
    score = 0.7 if success else 0.25
    total_tests = tests_passed + tests_failed
    if total_tests:
        score = 0.25 + 0.65 * (tests_passed / total_tests)
    if user_accepted is True:
        score += 0.1
    elif user_accepted is False:
        score -= 0.2
    return QualityScore(score=max(0.0, min(1.0, score)), tests_passed=tests_passed, tests_failed=tests_failed, user_accepted=user_accepted)
