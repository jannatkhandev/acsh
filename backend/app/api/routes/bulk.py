import json
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from ...dependencies.classifier import ClassifierDep

router = APIRouter(prefix="/bulk", tags=["bulk"])

@router.post("/")
async def bulk_classify(file: UploadFile, classifier: ClassifierDep):
    tickets = json.loads(await file.read())
    async def stream_results():
        for ticket in tickets:
            query = f"Subject: {ticket['subject']}\nBody: {ticket['body']}"
            classification = await classifier.classify(query)
            yield f"data: {json.dumps({'id': ticket['id'], 'classification': classification.model_dump()})}\n\n"
    
    return StreamingResponse(stream_results(), media_type="text/event-stream")