import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def main():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with open(
            "d:/elfie-lab-analyzer/pdfs/hard/var_innoquest_cardiometabolic_mixed_page_order.pdf",
            "rb",
        ) as f:
            pdf_bytes = f.read()
        res = await client.post(
            "/api/upload", files={"file": ("test.pdf", pdf_bytes, "application/pdf")}
        )
        print(res.status_code)
        print(res.json())


if __name__ == "__main__":
    asyncio.run(main())
