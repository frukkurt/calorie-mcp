import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from mcp.server.fastmcp import FastMCP
from supabase import create_client, Client


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
USER_ID = os.getenv("USER_ID", "fruk")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

mcp = FastMCP("Body Tracker", stateless_http=True)


def now_utc():
    return datetime.now(timezone.utc)


def day_range(days_ago: int = 0):
    target = now_utc().date() - timedelta(days=days_ago)
    start = f"{target}T00:00:00+00:00"
    end = f"{target}T23:59:59+00:00"
    return target.isoformat(), start, end


@mcp.tool()
def add_food(
    food_name: str,
    calories: int,
    meal: Optional[str] = None,
    protein_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    note: Optional[str] = None,
) -> dict:
    """Add food, calories, and macros."""

    row = {
        "user_id": USER_ID,
        "eaten_at": now_utc().isoformat(),
        "meal": meal,
        "food_name": food_name,
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "note": note,
    }

    result = supabase.table("food_logs").insert(row).execute()

    return {
        "status": "success",
        "message": f"บันทึกอาหารแล้ว: {food_name}",
        "data": result.data,
    }


@mcp.tool()
def add_weight(
    weight_kg: float,
    bodyfat_pct: Optional[float] = None,
    note: Optional[str] = None,
) -> dict:
    """Add body weight and optional body fat percentage."""

    row = {
        "user_id": USER_ID,
        "measured_at": now_utc().isoformat(),
        "weight_kg": weight_kg,
        "bodyfat_pct": bodyfat_pct,
        "note": note,
    }

    result = supabase.table("weight_logs").insert(row).execute()

    return {
        "status": "success",
        "message": f"บันทึกน้ำหนักแล้ว: {weight_kg} kg",
        "data": result.data,
    }


@mcp.tool()
def add_workout(
    workout_type: str,
    duration_min: Optional[int] = None,
    calories_burned: Optional[int] = None,
    distance_km: Optional[float] = None,
    avg_hr: Optional[int] = None,
    note: Optional[str] = None,
) -> dict:
    """Add workout log such as run, weight training, HYROX, zone 2, interval, etc."""

    row = {
        "user_id": USER_ID,
        "workout_at": now_utc().isoformat(),
        "workout_type": workout_type,
        "duration_min": duration_min,
        "calories_burned": calories_burned,
        "distance_km": distance_km,
        "avg_hr": avg_hr,
        "note": note,
    }

    result = supabase.table("workout_logs").insert(row).execute()

    return {
        "status": "success",
        "message": f"บันทึก workout แล้ว: {workout_type}",
        "data": result.data,
    }


@mcp.tool()
def today_summary() -> dict:
    """Summarize today's food, calories, macros, workout, and latest weight."""

    today, start, end = day_range(0)

    food_result = (
        supabase.table("food_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("eaten_at", start)
        .lte("eaten_at", end)
        .execute()
    )

    workout_result = (
        supabase.table("workout_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("workout_at", start)
        .lte("workout_at", end)
        .execute()
    )

    weight_result = (
        supabase.table("weight_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .order("measured_at", desc=True)
        .limit(1)
        .execute()
    )

    foods = food_result.data or []
    workouts = workout_result.data or []
    latest_weight = weight_result.data[0] if weight_result.data else None

    return {
        "date": today,
        "food_count": len(foods),
        "total_calories": sum(x.get("calories") or 0 for x in foods),
        "total_protein_g": sum(x.get("protein_g") or 0 for x in foods),
        "total_carbs_g": sum(x.get("carbs_g") or 0 for x in foods),
        "total_fat_g": sum(x.get("fat_g") or 0 for x in foods),
        "workout_count": len(workouts),
        "total_workout_duration_min": sum(x.get("duration_min") or 0 for x in workouts),
        "total_distance_km": sum(x.get("distance_km") or 0 for x in workouts),
        "total_calories_burned": sum(x.get("calories_burned") or 0 for x in workouts),
        "latest_weight": latest_weight,
        "foods": foods,
        "workouts": workouts,
    }


@mcp.tool()
def weekly_report() -> dict:
    """Summarize the last 7 days."""

    end_dt = now_utc()
    start_dt = end_dt - timedelta(days=7)

    food_result = (
        supabase.table("food_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("eaten_at", start_dt.isoformat())
        .lte("eaten_at", end_dt.isoformat())
        .execute()
    )

    workout_result = (
        supabase.table("workout_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("workout_at", start_dt.isoformat())
        .lte("workout_at", end_dt.isoformat())
        .execute()
    )

    weight_result = (
        supabase.table("weight_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("measured_at", start_dt.isoformat())
        .lte("measured_at", end_dt.isoformat())
        .order("measured_at", desc=False)
        .execute()
    )

    foods = food_result.data or []
    workouts = workout_result.data or []
    weights = weight_result.data or []

    days = 7

    return {
        "period": "last_7_days",
        "total_calories": sum(x.get("calories") or 0 for x in foods),
        "avg_calories_per_day": round(sum(x.get("calories") or 0 for x in foods) / days, 1),
        "total_protein_g": sum(x.get("protein_g") or 0 for x in foods),
        "avg_protein_per_day": round(sum(x.get("protein_g") or 0 for x in foods) / days, 1),
        "workout_count": len(workouts),
        "total_workout_duration_min": sum(x.get("duration_min") or 0 for x in workouts),
        "total_distance_km": sum(x.get("distance_km") or 0 for x in workouts),
        "weight_start": weights[0] if weights else None,
        "weight_latest": weights[-1] if weights else None,
        "foods_count": len(foods),
        "workouts": workouts,
        "weights": weights,
    }


@mcp.tool()
def hyrox_progress() -> dict:
    """Summarize HYROX-related progress from workout logs."""

    end_dt = now_utc()
    start_dt = end_dt - timedelta(days=30)

    workout_result = (
        supabase.table("workout_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("workout_at", start_dt.isoformat())
        .lte("workout_at", end_dt.isoformat())
        .execute()
    )

    workouts = workout_result.data or []

    run_workouts = [
        x for x in workouts
        if x.get("workout_type") and "run" in x.get("workout_type").lower()
    ]

    hyrox_workouts = [
        x for x in workouts
        if x.get("workout_type")
        and (
            "hyrox" in x.get("workout_type").lower()
            or "sled" in x.get("workout_type").lower()
            or "wall ball" in x.get("workout_type").lower()
            or "farmer" in x.get("workout_type").lower()
            or "row" in x.get("workout_type").lower()
            or "ski" in x.get("workout_type").lower()
        )
    ]

    strength_workouts = [
        x for x in workouts
        if x.get("workout_type")
        and (
            "weight" in x.get("workout_type").lower()
            or "strength" in x.get("workout_type").lower()
            or "leg" in x.get("workout_type").lower()
            or "push" in x.get("workout_type").lower()
            or "pull" in x.get("workout_type").lower()
        )
    ]

    return {
        "period": "last_30_days",
        "total_workouts": len(workouts),
        "run_sessions": len(run_workouts),
        "hyrox_specific_sessions": len(hyrox_workouts),
        "strength_sessions": len(strength_workouts),
        "total_running_distance_km": sum(x.get("distance_km") or 0 for x in run_workouts),
        "total_training_duration_min": sum(x.get("duration_min") or 0 for x in workouts),
        "summary": {
            "running_base": "มีข้อมูลวิ่ง" if run_workouts else "ยังไม่มีข้อมูลวิ่ง",
            "hyrox_specific": "มีซ้อมเฉพาะ HYROX" if hyrox_workouts else "ยังไม่มีซ้อมเฉพาะ HYROX",
            "strength": "มีเวท/strength" if strength_workouts else "ยังไม่มีข้อมูลเวท",
        },
        "recent_workouts": workouts[-10:],
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
    )