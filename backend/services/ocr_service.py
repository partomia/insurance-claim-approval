from services.policy_context_service import PolicyContextService

_ctx = PolicyContextService()


def extract_text(file_path: str) -> str:
    return _ctx._ocr_file(file_path)


class OCRService:
    extract_text = staticmethod(extract_text)


ocr_service = OCRService()
