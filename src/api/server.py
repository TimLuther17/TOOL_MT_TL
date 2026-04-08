import glob
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = r"C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass"

app = FastAPI(title="TOOL GTFS Overpass API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Job:
    def __init__(self, command):
        self.id = str(uuid.uuid4())
        self.command = command
        self.status = "queued"
        self.logs = []
        self.return_code = None
        self.created_at = datetime.now().isoformat()


jobs = {}


class RoutingPayload(BaseModel):
    mode: str = "raw"
    city: str | None = None
    bus: str | None = None
    selection: str = "a"
    visualize: bool = False


class UmlaufPayload(BaseModel):
    mode: str
    city: str
    bus: str
    accel_idx: str = "0"
    scenario_idx: str = "2"
    file_idx: str = "a"
    umlauf: str = ""
    excel_idx: str = "0"


class SimulationPayload(BaseModel):
    provider: str
    city: str
    bus: str
    file_idx: str = "a"
    date: str
    accel_idx: str = "0"
    scenario_idx: str = "2"
    variant: str = "G4"
    cleanup: bool = False


def list_dirs(path):
    if not os.path.exists(path):
        return []
    return [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]


def start_job(command):
    job = Job(command)
    jobs[job.id] = job

    def _runner():
        job.status = "running"
        proc = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            job.logs.append(line.rstrip("\n"))
        proc.wait()
        job.return_code = proc.returncode
        job.status = "success" if proc.returncode == 0 else "error"

    threading.Thread(target=_runner, daemon=True).start()
    return job


@app.get("/api/options")
def get_options():
    route_base = os.path.join(BASE_DIR, "1_data_route", "05_final_route")
    provider_base = os.path.join(BASE_DIR, "3_data_speed_profile")
    return {
        "route_cities": list_dirs(route_base),
        "providers": list_dirs(provider_base),
    }


@app.get("/api/options/routes")
def get_route_options():
    route_base = os.path.join(BASE_DIR, "1_data_route", "05_final_route")
    out = {}
    for city in list_dirs(route_base):
        city_path = os.path.join(route_base, city)
        out[city] = list_dirs(city_path)
    return out


@app.get("/api/options/simulation")
def get_simulation_options():
    base = os.path.join(BASE_DIR, "3_data_speed_profile")
    out = {}
    for provider in list_dirs(base):
        out[provider] = {}
        provider_path = os.path.join(base, provider)
        for city in list_dirs(provider_path):
            out[provider][city] = {}
            city_path = os.path.join(provider_path, city)
            for bus in list_dirs(city_path):
                files = [os.path.basename(p) for p in glob.glob(os.path.join(city_path, bus, "*.csv"))]
                out[provider][city][bus] = files
    return out


@app.get("/api/options/umlauf")
def get_umlauf_options():
    base = os.path.join(BASE_DIR, "2_data_fahrplan_umlauf")
    out = {}
    for provider in list_dirs(base):
        out[provider] = {}
        provider_path = os.path.join(base, provider)
        for city in list_dirs(provider_path):
            out[provider][city] = {}
            city_path = os.path.join(provider_path, city)
            for bus in list_dirs(city_path):
                files = [os.path.basename(p) for p in glob.glob(os.path.join(city_path, bus, "*.csv"))]
                out[provider][city][bus] = files
    return out


@app.post("/api/run/routing")
def run_routing(payload: RoutingPayload):
    cmd = [sys.executable, "1_main_routing.py", "--mode", payload.mode]
    if payload.city:
        cmd.extend(["--city", payload.city])
    if payload.bus:
        cmd.extend(["--bus", payload.bus])
    cmd.extend(["--selection", payload.selection])
    if payload.visualize:
        cmd.append("--visualize")
    job = start_job(cmd)
    return {"job_id": job.id, "status": job.status}


@app.post("/api/run/umlauf")
def run_umlauf(payload: UmlaufPayload):
    cmd = [
        sys.executable,
        "2_main_umlauf_base_Speed.py",
        "--mode",
        payload.mode,
        "--city",
        payload.city,
        "--bus",
        payload.bus,
        "--accel-idx",
        payload.accel_idx,
        "--scenario-idx",
        payload.scenario_idx,
        "--file-idx",
        payload.file_idx,
        "--umlauf",
        payload.umlauf,
        "--excel-idx",
        payload.excel_idx,
    ]
    job = start_job(cmd)
    return {"job_id": job.id, "status": job.status}


@app.post("/api/run/simulation")
def run_simulation(payload: SimulationPayload):
    cmd = [
        sys.executable,
        "3_main_temp_sim.py",
        "--mode",
        "run",
        "--provider",
        payload.provider,
        "--city",
        payload.city,
        "--bus",
        payload.bus,
        "--file-idx",
        payload.file_idx,
        "--date",
        payload.date,
        "--accel-idx",
        payload.accel_idx,
        "--scenario-idx",
        payload.scenario_idx,
        "--variant",
        payload.variant,
    ]
    if payload.cleanup:
        cmd.append("--cleanup")
    job = start_job(cmd)
    return {"job_id": job.id, "status": job.status}


@app.get("/api/jobs/{job_id}/logs")
def get_job_logs(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "status": job.status,
        "return_code": job.return_code,
        "logs": job.logs[-500:],
    }


@app.get("/api/results")
def get_results():
    roots = [
        ("sim", os.path.join(BASE_DIR, "5_data_bus_SIM")),
        ("results", os.path.join(BASE_DIR, "6_results")),
    ]
    files = []
    for kind, root in roots:
        if not os.path.exists(root):
            continue
        for ext in ("*.csv", "*.png", "*.html"):
            for path in glob.glob(os.path.join(root, "**", ext), recursive=True):
                rel = os.path.relpath(path, BASE_DIR).replace("\\", "/")
                files.append({"kind": kind, "path": rel, "name": os.path.basename(path), "url": f"/files/{rel}"})
    return {"files": files}


app.mount("/files", StaticFiles(directory=BASE_DIR), name="files")
