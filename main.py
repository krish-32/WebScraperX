from typing import Union
from fastapi import FastAPI, Request, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from libpostal.scrapping import scrape_businesses 
import json
import jinja2


app = FastAPI()

templates = Jinja2Templates(directory="templates")
templates.env.filters['escapejs'] = jinja2.filters.escape

@app.get("/", response_class=HTMLResponse)
async def read_root(
    request: Request,
    query: str = Query("", description="Search query"),
    page_count: int = Query(0, description="Number of pages to scrape"),
):
    data = scrape_businesses(query=query, page=page_count)
    data_json = json.dumps(data)
    #print(query,page_count)
    return templates.TemplateResponse(
        "data_table.html",
        {
            "request": request,
            "data_json": data_json,
            "data": data,
            "query": query,
            "page_count": page_count,
        },
    )

