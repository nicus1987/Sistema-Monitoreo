import asyncio
import json

from monitoreo import simulator as sim
from monitoreo.stream.consumer import process_stream


def test_stream_processing_with_dlq(service):
    msgs = [json.dumps(e).encode() for e in sim.sanctions()] + [b'{"no": "valido"}']
    out: list[tuple[str, bytes, bytes]] = []

    async def source():
        for m in msgs:
            yield m

    async def sink(topic, key, value):
        out.append((topic, key, value))

    processed = asyncio.run(process_stream(service, source(), sink))
    assert processed == 1
    assert out[0][0] == "monitoreo.decisions" and json.loads(out[0][2])["action"] == "DECLINE"
    assert out[1][0] == "monitoreo.dlq"
