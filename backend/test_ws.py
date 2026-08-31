import asyncio
import websockets

async def test():
    uri = "ws://localhost:8001/v1/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyMmM0OTFiNy03YjIxLTQ1MzItYTIzMy1lZWUzMmQ0OTRjZmQiLCJyb2xlIjoiaW52ZXN0aWdhdG9yIiwianVyaXNkaWN0aW9uX2lkIjoiMTJkMWQ5YTEtZDA0Yy00NzE1LTg2YzktM2NkMjFhMjM5ZjNmIiwiYmFua19pZCI6bnVsbCwiZXhwIjoxNzg4MTk1NDI1fQ.n5Q6GLIDvSpah9TX5WZlWc5G7BXds53AWvZUHasPlX0&jurisdiction_id=12d1d9a1-d04c-4715-86c9-3cd21a239f3f"
    try:
        async with websockets.connect(uri) as ws:
            print("Connected!")
    except Exception as e:
        print(f"Failed: {e}")

asyncio.run(test())
