"""SQLAlchemy persistence for Clip Evaluations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import sessionmaker

from clipfactory.domain.models import Action, Evaluation, EvaluationLayer, Issue
from clipfactory.infrastructure.db.models import EvaluationRow


class EvaluationRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def save(self, evaluation: Evaluation) -> None:
        with self.sessions.begin() as session:
            session.add(
                EvaluationRow(
                    id=evaluation.id,
                    run_id=evaluation.run_id,
                    clip_id=evaluation.clip_id,
                    attempt=evaluation.attempt,
                    layer=evaluation.layer.value,
                    passed=evaluation.passed,
                    issues=[item.model_dump(mode="json") for item in evaluation.issues],
                    warnings=[item.model_dump(mode="json") for item in evaluation.warnings],
                    actions=[item.model_dump(mode="json") for item in evaluation.actions],
                    metrics=evaluation.metrics,
                    evaluator=evaluation.evaluator,
                    created_at=evaluation.created_at,
                )
            )

    def get(self, evaluation_id: UUID) -> Evaluation | None:
        with self.sessions() as session:
            row = session.get(EvaluationRow, evaluation_id)
            if row is None:
                return None
            return Evaluation(
                id=row.id,
                run_id=row.run_id,
                clip_id=row.clip_id,
                attempt=row.attempt,
                layer=EvaluationLayer(row.layer),
                issues=[Issue.model_validate(item) for item in row.issues],
                warnings=[Issue.model_validate(item) for item in row.warnings],
                actions=[Action.model_validate(item) for item in row.actions],
                metrics=row.metrics,
                evaluator=row.evaluator,
                created_at=row.created_at,
            )
