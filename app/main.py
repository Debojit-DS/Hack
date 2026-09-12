import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse

from app.api.routes import router as api_router
from app.data.villages import VILLAGES
from app.data.sensor_simulator import sensor_network
from app.data.translations import TRANSLATIONS
from app.models.ml_model import build_feature_row, predict
from app.alerts.alert_engine import alert_engine

TICK_SECONDS = 4


async def simulation_loop():
    while True:
        await asyncio.sleep(TICK_SECONDS)
        sensor_network.tick_all()
        for village in VILLAGES:
            state = sensor_network.get(village["id"])
            snapshot = state.snapshot()
            features = build_feature_row(village, snapshot)
            risk = predict(features)
            alert_engine.evaluate(village, risk, snapshot)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(simulation_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Hyper-Local Flash Flood & Landslide Early Warning System", lifespan=lifespan)

app.include_router(api_router, prefix="/api")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    lang = request.cookies.get("meghdrishti_lang", "en")
    if lang not in TRANSLATIONS:
        lang = "en"
    return templates.TemplateResponse(
        request,
        "index.html",
        {"translations": TRANSLATIONS[lang], "lang": lang, "all_translations": TRANSLATIONS},
    )


@app.post("/set-language/{lang_code}")
async def set_language(request: Request, lang_code: str):
    response = HTMLResponse(content='{"ok":true}', media_type="application/json")
    if lang_code in TRANSLATIONS:
        response.set_cookie(key="meghdrishti_lang", value=lang_code, max_age=60 * 60 * 24 * 365, httponly=False)
    return response
