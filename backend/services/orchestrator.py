import logging
import threading

from config import get_settings
from services.claim_pipeline import run_claim_pipeline

logger = logging.getLogger(__name__)
settings = get_settings()


def _pipeline_entrypoint():
    """Return the callable used to process a claim end-to-end.

    Routes to `crew.flow.run_claim_flow` when `settings.use_crewai_flow` is
    truthy, otherwise the legacy `run_claim_pipeline`. Kept as a function
    (not module-level constant) so config changes at runtime take effect
    without a re-import.
    """
    if settings.use_crewai_flow:
        try:
            from crew.flow import run_claim_flow

            return run_claim_flow
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "CrewAI Flow unavailable (%s), falling back to legacy pipeline", exc
            )
    return run_claim_pipeline


class ClaimOrchestrator:
    def dispatch(self, claim_id: int) -> None:
        if settings.claim_processing_mode == "sync":
            self._run_sync(claim_id)
            return
        if settings.claim_processing_mode == "celery":
            self._run_celery(claim_id)
            return
        # auto — prefer Celery, fall back to in-process sync
        try:
            self._run_celery(claim_id)
        except Exception as exc:
            logger.warning("Celery unavailable (%s), running sync pipeline", exc)
            self._run_sync(claim_id)

    def _run_celery(self, claim_id: int) -> None:
        from tasks.claim_tasks import orchestrate_claim_task

        orchestrate_claim_task.delay(claim_id)

    def dispatch_from_step(self, claim_id: int, from_step: str) -> None:
        if settings.claim_processing_mode == "sync":
            thread = threading.Thread(
                target=self._run_from_step,
                args=(claim_id, from_step),
                daemon=True,
            )
            thread.start()
            return
        if settings.claim_processing_mode == "celery":
            try:
                from tasks.claim_tasks import orchestrate_claim_from_step_task
                orchestrate_claim_from_step_task.delay(claim_id, from_step)
                return
            except Exception as exc:
                logger.warning("Celery from_step unavailable (%s), running sync", exc)
        thread = threading.Thread(
            target=self._run_from_step,
            args=(claim_id, from_step),
            daemon=True,
        )
        thread.start()

    def _run_from_step(self, claim_id: int, from_step: str) -> None:
        from services.claim_pipeline import run_claim_pipeline_from
        run_claim_pipeline_from(claim_id, from_step)

    def _run_sync(self, claim_id: int) -> None:
        target = _pipeline_entrypoint()
        thread = threading.Thread(target=target, args=(claim_id,), daemon=True)
        thread.start()
