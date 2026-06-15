from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True)
class BanditArm:
    model: str
    pulls: int = 0
    total_reward: float = 0.0

    @property
    def average_reward(self) -> float:
        return self.total_reward / self.pulls if self.pulls else 0.0


class EpsilonGreedyRouter:
    def __init__(self, *, epsilon: float = 0.1, rng: random.Random | None = None) -> None:
        self.epsilon = max(0.0, min(1.0, float(epsilon)))
        self.rng = rng or random.Random()
        self.arms: dict[str, BanditArm] = {}

    def choose(self, candidates: Iterable[str]) -> str:
        rows = [str(candidate) for candidate in candidates]
        if not rows:
            raise ValueError("Cannot choose without candidates")
        for model in rows:
            self.arms.setdefault(model, BanditArm(model=model))
        if self.rng.random() < self.epsilon:
            return self.rng.choice(rows)
        return max(rows, key=lambda model: (self.arms[model].average_reward, -self.arms[model].pulls, model))

    def record(self, model: str, reward: float) -> None:
        arm = self.arms.setdefault(model, BanditArm(model=model))
        arm.pulls += 1
        arm.total_reward += float(reward)


def reward(
    *,
    validation_score: float,
    token_cost_penalty: float = 0.0,
    latency_penalty: float = 0.0,
    retry_penalty: float = 0.0,
) -> float:
    return float(validation_score) - float(token_cost_penalty) - float(latency_penalty) - float(retry_penalty)


__all__ = ["BanditArm", "EpsilonGreedyRouter", "reward"]
