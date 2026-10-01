"""
fetch-urls — асинхронная параллельная загрузка URL-ов.
"""
import asyncio

DESCRIPTION = "Асинхронно скачать несколько URL"

# обычный синхронный execute — для thread/subprocess-режимов
def execute(context):
    import asyncio
    return asyncio.run(_run_async(context))

# приоритетный для AsyncScheduler:
async def execute_async(context):
    return await _run_async(context)


async def _run_async(context):
    import aiohttp

    urls = (context['args'].get('urls') or '').split(',')
    urls = [u.strip() for u in urls if u.strip()]
    if not urls:
        print("Укажите --urls=url1,url2,...")
        return 1

    async with aiohttp.ClientSession() as session:
        tasks = [_fetch(session, u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for url, r in zip(urls, results):
        if isinstance(r, Exception):
            print(f"❌ {url}: {r}")
        else:
            print(f"✔ {url}: {r} bytes")

    return 0


async def _fetch(session, url):
    async with session.get(url, timeout=30) as resp:
        body = await resp.read()
        return len(body)
