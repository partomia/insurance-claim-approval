import logging
import threading

from config import get_settings
from services.claim_pipeline import run_claim_pipeline

logger = logging.getLogger(__name__)
settings = get_settings()


class ClaimOrchestrator:
    def dispatch(self, claim_id: int) -> None:
        if settings.claim_processing_mode == "sync":
            self._run_sync(claim_id)
            return
        if settings.claim_processing_mode == "celery":
            self._run_celery(claim_id)
            return
        # auto: SQLite local dev runs in-process; otherwise prefer Celery
        if settings.database_url.startswith("sqlite"):
            self._run_sync(claim_id)
            return
        try:
            self._run_celery(claim_id)
        except Exception as exc:
            logger.warning("Celery unavailable (%s), running sync pipeline", exc)
            self._run_sync(claim_id)

    def _run_celery(self, claim_id: int) -> None:
        from tasks.claim_tasks import orchestrate_claim_task

        orchestrate_claim_task.delay(claim_id)

    def dispatch_from_step(self, claim_id: int, from_step: str) -> None:
        if settings.claim_processing_mode == "sync" or settings.database_url.startswith("sqlite"):
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
        thread = threading.Thread(target=run_claim_pipeline, args=(claim_id,), daemon=True)
        thread.start()
