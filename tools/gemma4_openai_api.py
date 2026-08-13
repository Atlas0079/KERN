from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from typing import Any

import torch
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from transformers import AutoModelForMultimodalLM, AutoProcessor, TextIteratorStreamer


DEFAULT_MODEL_PATH = "/mnt/nv1/home/BA24204058/gemma-4-31B-it"
DEFAULT_MODEL_NAME = "gemma-4-31B-it"


class ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = False


class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


class ChatServer:
    def __init__(
        self,
        model_path: str,
        model_name: str,
        api_key: str,
        enable_thinking: bool,
        device: str,
    ) -> None:
        self.model_path = model_path
        self.model_name = model_name
        self.api_key = api_key
        self.enable_thinking = enable_thinking
        self.device = self.resolve_cuda_device(device)
        self.lock = threading.Lock()

        print(f"Loading model from {self.model_path} onto {self.device}", flush=True)
        self.processor = AutoProcessor.from_pretrained(self.model_path, local_files_only=True)
        self.model = AutoModelForMultimodalLM.from_pretrained(
            self.model_path,
            dtype=torch.bfloat16,
            device_map={"": self.device.index},
            local_files_only=True,
        )
        self.model.eval()
        self.max_context_tokens = int(self.model.config.text_config.max_position_embeddings)
        print(f"Model loaded on {self.device}", flush=True)

    @staticmethod
    def resolve_cuda_device(value: str) -> torch.device:
        device = torch.device(value)
        if device.type != "cuda":
            raise ValueError(f"--device must name a CUDA device, got {value!r}")
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable; Gemma 4 requires a CUDA device")

        index = 0 if device.index is None else device.index
        if index >= torch.cuda.device_count():
            raise ValueError(
                f"CUDA device {index} is unavailable; "
                f"{torch.cuda.device_count()} device(s) are visible"
            )
        return torch.device(f"cuda:{index}")

    def check_auth(self, authorization: str | None) -> None:
        if not self.api_key:
            return
        if authorization != f"Bearer {self.api_key}":
            raise HTTPException(status_code=401, detail="invalid api key")

    def normalize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, str]] = []
        for msg in messages:
            role = str(msg.get("role", "user") or "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text", "")))
                content = "".join(parts)
            normalized.append({"role": role, "content": str(content)})
        return normalized

    def generate(self, req: ChatRequest) -> str:
        messages = self.normalize_messages(req.messages)
        with self.lock:
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                add_generation_prompt=True,
                enable_thinking=self.enable_thinking,
            )
            inputs = inputs.to(self.device)
            input_len = inputs["input_ids"].shape[-1]

            with torch.inference_mode():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens(req.max_tokens, input_len),
                    do_sample=float(req.temperature) > 0,
                    temperature=max(float(req.temperature), 1e-5),
                    top_p=float(req.top_p),
                )

            raw = self.processor.decode(outputs[0][input_len:], skip_special_tokens=False)
            try:
                parsed = self.processor.parse_response(raw, prefix=inputs["input_ids"])
            except Exception:
                return raw
            if isinstance(parsed, str):
                return parsed
            if isinstance(parsed, dict):
                for key in ("answer", "content", "text", "response"):
                    value = parsed.get(key)
                    if value is not None:
                        return str(value)
            return str(parsed)

    def generate_stream(self, req: ChatRequest):
        messages = self.normalize_messages(req.messages)
        with self.lock:
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                add_generation_prompt=True,
                enable_thinking=self.enable_thinking,
            )
            inputs = inputs.to(self.device)
            input_len = inputs["input_ids"].shape[-1]
            streamer = TextIteratorStreamer(
                self.processor,
                skip_prompt=True,
                skip_special_tokens=False,
            )
            failure: list[BaseException] = []

            def run_generation() -> None:
                try:
                    with torch.inference_mode():
                        self.model.generate(
                            **inputs,
                            max_new_tokens=self.max_new_tokens(req.max_tokens, input_len),
                            do_sample=float(req.temperature) > 0,
                            temperature=max(float(req.temperature), 1e-5),
                            top_p=float(req.top_p),
                            streamer=streamer,
                        )
                except BaseException as error:
                    failure.append(error)
                    streamer.end()

            thread = threading.Thread(target=run_generation, daemon=True)
            thread.start()
            for text in streamer:
                yield text
            thread.join()
            if failure:
                raise failure[0]

    def max_new_tokens(self, requested_max_tokens: int | None, input_len: int) -> int:
        available = self.max_context_tokens - input_len
        if available < 1:
            raise ValueError(
                f"the {input_len}-token prompt reaches the model context limit "
                f"of {self.max_context_tokens} tokens"
            )
        if requested_max_tokens is None:
            return available
        if requested_max_tokens > available:
            raise ValueError(
                f"max_tokens={requested_max_tokens} exceeds the {available} tokens "
                "remaining in the model context"
            )
        return requested_max_tokens

    @staticmethod
    def answer_stream(texts):
        """Drop Gemma's thinking channel before emitting OpenAI delta content."""
        marker = "<channel|>"
        buffer = ""
        answer_started = False
        for text in texts:
            if answer_started:
                yield text
                continue
            buffer += text
            marker_index = buffer.find(marker)
            if marker_index >= 0:
                answer_started = True
                answer = buffer[marker_index + len(marker):]
                if answer:
                    yield answer
            elif len(buffer) >= 128:
                # A future template may omit the thinking channel. Avoid
                # indefinitely withholding an ordinary direct response.
                answer_started = True
                yield buffer
        if not answer_started and buffer:
            yield buffer


def create_app(server: ChatServer) -> FastAPI:
    app = FastAPI(title="Gemma 4 OpenAI-compatible API", default_response_class=Utf8JSONResponse)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "model": server.model_name,
            "cuda_available": torch.cuda.is_available(),
            "device_count": torch.cuda.device_count(),
            "device": str(server.device),
            "max_context_tokens": server.max_context_tokens,
        }

    @app.get("/v1/models")
    def models(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        server.check_auth(authorization)
        return {
            "object": "list",
            "data": [
                {
                    "id": server.model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "local",
                }
            ],
        }

    @app.post("/v1/chat/completions", response_model=None)
    def chat(req: ChatRequest, authorization: str | None = Header(default=None)) -> dict[str, Any] | StreamingResponse:
        server.check_auth(authorization)
        if req.model != server.model_name:
            raise HTTPException(status_code=404, detail=f"unknown model: {req.model}")
        if not req.messages:
            raise HTTPException(status_code=400, detail="messages must be non-empty")

        if req.stream:
            response_id = f"chatcmpl-{uuid.uuid4().hex}"
            created = int(time.time())

            def stream_response():
                initial = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": server.model_name,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(initial, ensure_ascii=False, separators=(',', ':'))}\n\n"
                for text in server.answer_stream(server.generate_stream(req)):
                    if not text:
                        continue
                    chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": server.model_name,
                        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
                final = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": server.model_name,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(final, ensure_ascii=False, separators=(',', ':'))}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                stream_response(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        text = server.generate(req)
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": server.model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", default=os.environ.get("GEMMA4_MODEL_PATH", DEFAULT_MODEL_PATH))
    parser.add_argument("--model-name", default=os.environ.get("GEMMA4_MODEL_NAME", DEFAULT_MODEL_NAME))
    parser.add_argument("--api-key", default=os.environ.get("GEMMA4_API_KEY"))
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument(
        "--device",
        default=os.environ.get("GEMMA4_DEVICE", "cuda:0"),
        help="CUDA device for this replica, for example cuda:0 or cuda:1",
    )
    parser.add_argument("--host", default=os.environ.get("GEMMA4_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("GEMMA4_PORT", "8080")))
    return parser.parse_args()


args = parse_args()
if not args.api_key:
    raise SystemExit("Set GEMMA4_API_KEY or pass --api-key before starting the service.")
gemma_server = ChatServer(
    model_path=args.model_path,
    model_name=args.model_name,
    api_key=args.api_key,
    enable_thinking=bool(args.enable_thinking),
    device=args.device,
)
app = create_app(gemma_server)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, workers=1)
