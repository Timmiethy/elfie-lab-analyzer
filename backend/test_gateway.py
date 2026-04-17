import asyncio

from app.services.input_gateway import InputGateway


async def main():
    gw = InputGateway()
    res = await gw.classify(b"%PDF-text_based_dummy_bytes", "test.pdf", "application/pdf")
    print(res["lane_type"])


asyncio.run(main())
