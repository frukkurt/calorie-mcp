import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from mcp.server.fastmcp import FastMCP
from supabase import create_client, Client


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
USER_ID = os.getenv("USER_ID", "fruk")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

mcp = FastMCP("Body Tracker", stateless_http=True)


# -------------------------
# Helpers
# -------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def range_days(days: int = 7):
    end_dt = now_utc()
    start_dt = end_dt - timedelta(days=days)
    return start_dt.isoformat(), end_dt.isoformat()


def today_range():
    today = now_utc().date()
    start = f"{today}T00:00:00+00:00"
    end = f"{today}T23:59:59+00:00"
    return today.isoformat(), start, end


def safe_sum(rows: List[Dict[str, Any]], key: str) -> float:
    return float(sum(row.get(key) or 0 for row in rows))


def get_latest_goal() -> Optional[dict]:
    result = (
        supabase.table("user_goals")
        .select("*")
        .eq("user_id", USER_ID)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_latest_weight() -> Optional[dict]:
    result = (
        supabase.table("weight_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .order("measured_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


# -------------------------
# 🍚 Nutrition
# -------------------------

@mcp.tool()
def add_food(
    food_name: str,
    calories: int,
    meal: Optional[str] = None,
    protein_g: Optional[float] = None,
    carbs_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    serving_qty: Optional[float] = None,
    serving_unit: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Add a food log with calories and macros."""

    row = {
        "user_id": USER_ID,
        "eaten_at": iso_now(),
        "meal": meal,
        "food_name": food_name,
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "serving_qty": serving_qty,
        "serving_unit": serving_unit,
        "source": "manual",
        "confidence": 1.0,
        "note": note,
    }

    result = supabase.table("food_logs").insert(row).execute()

    return {
        "status": "success",
        "message": f"บันทึกอาหารแล้ว: {food_name}",
        "data": result.data,
    }


@mcp.tool()
def delete_food(log_id: str) -> dict:
    """Delete a food log by id."""

    result = (
        supabase.table("food_logs")
        .delete()
        .eq("id", log_id)
        .eq("user_id", USER_ID)
        .execute()
    )

    return {
        "status": "success",
        "deleted": result.data,
    }


@mcp.tool()
def search_food(keyword: Optional[str] = None, limit: int = 20) -> dict:
    """Search food logs by keyword or return recent food logs."""

    query = (
        supabase.table("food_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .order("eaten_at", desc=True)
        .limit(limit)
    )

    if keyword:
        query = query.ilike("food_name", f"%{keyword}%")

    result = query.execute()

    return {
        "keyword": keyword,
        "count": len(result.data or []),
        "foods": result.data or [],
    }


@mcp.tool()
def today_summary() -> dict:
    """Summarize today's calories, macros, workouts, and latest weight."""

    date, start, end = today_range()

    foods_result = (
        supabase.table("food_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("eaten_at", start)
        .lte("eaten_at", end)
        .order("eaten_at", desc=False)
        .execute()
    )

    workouts_result = (
        supabase.table("workout_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("workout_at", start)
        .lte("workout_at", end)
        .order("workout_at", desc=False)
        .execute()
    )

    foods = foods_result.data or []
    workouts = workouts_result.data or []
    goal = get_latest_goal()
    latest_weight = get_latest_weight()

    total_calories = safe_sum(foods, "calories")
    total_protein = safe_sum(foods, "protein_g")
    total_carbs = safe_sum(foods, "carbs_g")
    total_fat = safe_sum(foods, "fat_g")
    calories_burned = safe_sum(workouts, "calories_burned")

    calorie_goal = goal.get("calorie_goal") if goal else None
    protein_goal_g = goal.get("protein_goal_g") if goal else None

    return {
        "date": date,
        "nutrition": {
            "food_count": len(foods),
            "total_calories": total_calories,
            "total_protein_g": total_protein,
            "total_carbs_g": total_carbs,
            "total_fat_g": total_fat,
            "calorie_goal": calorie_goal,
            "calories_remaining": calorie_goal - total_calories if calorie_goal else None,
            "protein_goal_g": protein_goal_g,
            "protein_remaining_g": protein_goal_g - total_protein if protein_goal_g else None,
        },
        "workout": {
            "workout_count": len(workouts),
            "total_duration_min": safe_sum(workouts, "duration_min"),
            "total_distance_km": safe_sum(workouts, "distance_km"),
            "total_calories_burned": calories_burned,
        },
        "body": {
            "latest_weight": latest_weight,
        },
        "foods": foods,
        "workouts": workouts,
    }


@mcp.tool()
def weekly_report(days: int = 7) -> dict:
    """Summarize food, calories, macros, workouts, and weight for recent days."""

    start, end = range_days(days)

    foods_result = (
        supabase.table("food_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("eaten_at", start)
        .lte("eaten_at", end)
        .execute()
    )

    workouts_result = (
        supabase.table("workout_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("workout_at", start)
        .lte("workout_at", end)
        .execute()
    )

    weights_result = (
        supabase.table("weight_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("measured_at", start)
        .lte("measured_at", end)
        .order("measured_at", desc=False)
        .execute()
    )

    foods = foods_result.data or []
    workouts = workouts_result.data or []
    weights = weights_result.data or []

    return {
        "period_days": days,
        "nutrition": {
            "total_calories": safe_sum(foods, "calories"),
            "avg_calories_per_day": round(safe_sum(foods, "calories") / days, 1),
            "total_protein_g": safe_sum(foods, "protein_g"),
            "avg_protein_per_day": round(safe_sum(foods, "protein_g") / days, 1),
            "total_carbs_g": safe_sum(foods, "carbs_g"),
            "total_fat_g": safe_sum(foods, "fat_g"),
            "food_logs_count": len(foods),
        },
        "workout": {
            "workout_count": len(workouts),
            "total_duration_min": safe_sum(workouts, "duration_min"),
            "total_distance_km": safe_sum(workouts, "distance_km"),
            "total_calories_burned": safe_sum(workouts, "calories_burned"),
        },
        "weight": {
            "start": weights[0] if weights else None,
            "latest": weights[-1] if weights else None,
            "change_kg": float(weights[-1]["weight_kg"] - weights[0]["weight_kg"]) if len(weights) >= 2 else None,
        },
        "recent_workouts": workouts[-10:],
    }


# -------------------------
# ⚖️ Weight
# -------------------------

@mcp.tool()
def add_weight(
    weight_kg: float,
    bodyfat_pct: Optional[float] = None,
    note: Optional[str] = None,
) -> dict:
    """Add body weight and optional body fat percentage."""

    row = {
        "user_id": USER_ID,
        "measured_at": iso_now(),
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
def weight_history(days: int = 30, limit: int = 100) -> dict:
    """Get weight history."""

    start, end = range_days(days)

    result = (
        supabase.table("weight_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("measured_at", start)
        .lte("measured_at", end)
        .order("measured_at", desc=False)
        .limit(limit)
        .execute()
    )

    rows = result.data or []

    return {
        "period_days": days,
        "count": len(rows),
        "start_weight": rows[0] if rows else None,
        "latest_weight": rows[-1] if rows else None,
        "change_kg": float(rows[-1]["weight_kg"] - rows[0]["weight_kg"]) if len(rows) >= 2 else None,
        "weights": rows,
    }


@mcp.tool()
def bodyfat_history(days: int = 30, limit: int = 100) -> dict:
    """Get body fat percentage history."""

    start, end = range_days(days)

    result = (
        supabase.table("weight_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("measured_at", start)
        .lte("measured_at", end)
        .not_.is_("bodyfat_pct", "null")
        .order("measured_at", desc=False)
        .limit(limit)
        .execute()
    )

    rows = result.data or []

    return {
        "period_days": days,
        "count": len(rows),
        "start_bodyfat_pct": rows[0] if rows else None,
        "latest_bodyfat_pct": rows[-1] if rows else None,
        "change_pct": float(rows[-1]["bodyfat_pct"] - rows[0]["bodyfat_pct"]) if len(rows) >= 2 else None,
        "bodyfat_logs": rows,
    }


# -------------------------
# 🏃 Workout
# -------------------------

@mcp.tool()
def add_workout(
    workout_type: str,
    duration_min: Optional[int] = None,
    calories_burned: Optional[int] = None,
    distance_km: Optional[float] = None,
    avg_hr: Optional[int] = None,
    max_hr: Optional[int] = None,
    rpe: Optional[float] = None,
    note: Optional[str] = None,
) -> dict:
    """Add workout log such as run, weights, HYROX, zone 2, interval, etc."""

    row = {
        "user_id": USER_ID,
        "workout_at": iso_now(),
        "workout_type": workout_type,
        "duration_min": duration_min,
        "calories_burned": calories_burned,
        "distance_km": distance_km,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "rpe": rpe,
        "note": note,
    }

    result = supabase.table("workout_logs").insert(row).execute()

    return {
        "status": "success",
        "message": f"บันทึก workout แล้ว: {workout_type}",
        "data": result.data,
    }


@mcp.tool()
def workout_history(
    days: int = 30,
    workout_type_keyword: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """Get workout history, optionally filtered by workout type keyword."""

    start, end = range_days(days)

    query = (
        supabase.table("workout_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("workout_at", start)
        .lte("workout_at", end)
        .order("workout_at", desc=False)
        .limit(limit)
    )

    if workout_type_keyword:
        query = query.ilike("workout_type", f"%{workout_type_keyword}%")

    result = query.execute()
    rows = result.data or []

    return {
        "period_days": days,
        "filter": workout_type_keyword,
        "count": len(rows),
        "total_duration_min": safe_sum(rows, "duration_min"),
        "total_distance_km": safe_sum(rows, "distance_km"),
        "total_calories_burned": safe_sum(rows, "calories_burned"),
        "workouts": rows,
    }


@mcp.tool()
def hyrox_progress(days: int = 30) -> dict:
    """Summarize HYROX-related progress from workout logs."""

    start, end = range_days(days)

    result = (
        supabase.table("workout_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("workout_at", start)
        .lte("workout_at", end)
        .order("workout_at", desc=False)
        .execute()
    )

    workouts = result.data or []

    def has_any(text: str, keywords: List[str]) -> bool:
        text = (text or "").lower()
        return any(k in text for k in keywords)

    run_keywords = ["run", "วิ่ง", "zone 2", "tempo", "interval"]
    strength_keywords = ["weight", "strength", "leg", "push", "pull", "เวท", "ขา", "อก", "หลัง"]
    hyrox_keywords = ["hyrox", "sled", "wall ball", "farmer", "row", "ski", "burpee", "lunges"]

    run_workouts = [x for x in workouts if has_any(x.get("workout_type", "") + " " + str(x.get("note", "")), run_keywords)]
    strength_workouts = [x for x in workouts if has_any(x.get("workout_type", "") + " " + str(x.get("note", "")), strength_keywords)]
    hyrox_workouts = [x for x in workouts if has_any(x.get("workout_type", "") + " " + str(x.get("note", "")), hyrox_keywords)]

    return {
        "period_days": days,
        "total_workouts": len(workouts),
        "run_sessions": len(run_workouts),
        "strength_sessions": len(strength_workouts),
        "hyrox_specific_sessions": len(hyrox_workouts),
        "total_running_distance_km": safe_sum(run_workouts, "distance_km"),
        "total_training_duration_min": safe_sum(workouts, "duration_min"),
        "notes": {
            "running_base": "มีข้อมูลวิ่ง" if run_workouts else "ยังไม่มีข้อมูลวิ่ง",
            "strength_base": "มีข้อมูลเวท" if strength_workouts else "ยังไม่มีข้อมูลเวท",
            "hyrox_specific": "มีซ้อมเฉพาะ HYROX" if hyrox_workouts else "ยังไม่มีข้อมูลซ้อมเฉพาะ HYROX",
        },
        "recent_workouts": workouts[-10:],
    }


# -------------------------
# 📈 Analytics
# -------------------------

@mcp.tool()
def calorie_balance(days: int = 7) -> dict:
    """Estimate calorie intake, exercise calories, and net calories."""

    start, end = range_days(days)

    foods_result = (
        supabase.table("food_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("eaten_at", start)
        .lte("eaten_at", end)
        .execute()
    )

    workouts_result = (
        supabase.table("workout_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("workout_at", start)
        .lte("workout_at", end)
        .execute()
    )

    foods = foods_result.data or []
    workouts = workouts_result.data or []

    intake = safe_sum(foods, "calories")
    burned = safe_sum(workouts, "calories_burned")

    return {
        "period_days": days,
        "total_intake_calories": intake,
        "avg_intake_per_day": round(intake / days, 1),
        "exercise_calories_burned": burned,
        "estimated_net_calories": intake - burned,
        "note": "net calories นี้หักเฉพาะ calories_burned จาก workout ที่บันทึก ไม่รวม BMR/TDEE",
    }


@mcp.tool()
def protein_goal() -> dict:
    """Check protein progress against goal."""

    goal = get_latest_goal()
    date, start, end = today_range()

    foods_result = (
        supabase.table("food_logs")
        .select("*")
        .eq("user_id", USER_ID)
        .gte("eaten_at", start)
        .lte("eaten_at", end)
        .execute()
    )

    foods = foods_result.data or []
    protein_today = safe_sum(foods, "protein_g")
    protein_goal_g = goal.get("protein_goal_g") if goal else None

    return {
        "date": date,
        "protein_today_g": protein_today,
        "protein_goal_g": protein_goal_g,
        "remaining_g": protein_goal_g - protein_today if protein_goal_g else None,
        "progress_pct": round((protein_today / protein_goal_g) * 100, 1) if protein_goal_g else None,
        "note": "ถ้ายังไม่มี goal ให้เพิ่มใน user_goals ก่อน",
    }


@mcp.tool()
def weight_trend(days: int = 30) -> dict:
    """Analyze body weight trend."""

    history = weight_history(days=days)
    weights = history.get("weights", [])

    if len(weights) < 2:
        return {
            "period_days": days,
            "status": "not_enough_data",
            "message": "ต้องมีน้ำหนักอย่างน้อย 2 ครั้งเพื่อดู trend",
            "weights": weights,
        }

    start_w = float(weights[0]["weight_kg"])
    end_w = float(weights[-1]["weight_kg"])
    change = end_w - start_w
    avg_weekly_change = change / max(days / 7, 1)

    if change < -0.3:
        trend = "down"
    elif change > 0.3:
        trend = "up"
    else:
        trend = "stable"

    return {
        "period_days": days,
        "start_weight_kg": start_w,
        "latest_weight_kg": end_w,
        "change_kg": round(change, 2),
        "avg_weekly_change_kg": round(avg_weekly_change, 2),
        "trend": trend,
        "weights": weights,
    }


@mcp.tool()
def weekly_dashboard() -> dict:
    """Return combined weekly dashboard."""

    report = weekly_report(days=7)
    balance = calorie_balance(days=7)
    hyrox = hyrox_progress(days=7)
    trend = weight_trend(days=30)

    return {
        "weekly_report": report,
        "calorie_balance": balance,
        "hyrox_progress_7d": hyrox,
        "weight_trend_30d": trend,
    }


# -------------------------
# 🤖 AI / Estimation helpers
# -------------------------

FOOD_ESTIMATES = {
    "ข้าวกะเพราไก่ไข่ดาว": {"calories": 750, "protein_g": 35, "carbs_g": 80, "fat_g": 30},
    "กะเพราไก่ไข่ดาว": {"calories": 700, "protein_g": 35, "carbs_g": 70, "fat_g": 30},
    "ข้าวมันไก่": {"calories": 650, "protein_g": 30, "carbs_g": 75, "fat_g": 25},
    "ข้าวไข่เจียว": {"calories": 600, "protein_g": 20, "carbs_g": 70, "fat_g": 25},
    "อกไก่": {"calories": 165, "protein_g": 31, "carbs_g": 0, "fat_g": 4},
    "ไข่ต้ม": {"calories": 70, "protein_g": 6, "carbs_g": 1, "fat_g": 5},
    "ไข่ดาว": {"calories": 120, "protein_g": 6, "carbs_g": 1, "fat_g": 10},
    "เวย์": {"calories": 130, "protein_g": 25, "carbs_g": 3, "fat_g": 2},
    "นม": {"calories": 200, "protein_g": 10, "carbs_g": 20, "fat_g": 8},
    "แซนวิช": {"calories": 350, "protein_g": 18, "carbs_g": 40, "fat_g": 14},
}


def estimate_from_text_simple(text: str) -> dict:
    text_lower = text.lower()
    matched = []

    total = {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}

    for food, est in FOOD_ESTIMATES.items():
        if food.lower() in text_lower:
            qty = 1

            # simple Thai quantity detection: "ไข่ต้ม 2 ฟอง", "เวย์ 2 scoop"
            pattern = rf"{re.escape(food)}\s*(\d+)"
            m = re.search(pattern, text_lower)
            if m:
                qty = int(m.group(1))

            matched.append({"food_name": food, "qty": qty, **est})

            total["calories"] += est["calories"] * qty
            total["protein_g"] += est["protein_g"] * qty
            total["carbs_g"] += est["carbs_g"] * qty
            total["fat_g"] += est["fat_g"] * qty

    if not matched:
        return {
            "status": "low_confidence",
            "message": "ยังประเมินไม่ได้จาก keyword ที่มี ให้ ChatGPT ช่วยประมาณแล้วเรียก add_food แทน",
            "input": text,
            "estimate": None,
        }

    return {
        "status": "estimated",
        "input": text,
        "matched_foods": matched,
        "estimate": total,
        "confidence": 0.6,
    }


@mcp.tool()
def estimate_calories_from_text(text: str, save: bool = False, meal: Optional[str] = None) -> dict:
    """Estimate calories and macros from food text. Optionally save to food_logs."""

    estimate = estimate_from_text_simple(text)

    if save and estimate.get("estimate"):
        est = estimate["estimate"]
        row = {
            "user_id": USER_ID,
            "eaten_at": iso_now(),
            "meal": meal,
            "food_name": text,
            "calories": int(est["calories"]),
            "protein_g": est["protein_g"],
            "carbs_g": est["carbs_g"],
            "fat_g": est["fat_g"],
            "source": "text_estimate",
            "confidence": estimate.get("confidence", 0.5),
            "note": "Auto-estimated from text",
        }
        result = supabase.table("food_logs").insert(row).execute()
        estimate["saved"] = result.data

    return estimate


@mcp.tool()
def estimate_calories_from_image(
    image_description: str,
    save: bool = False,
    meal: Optional[str] = None,
) -> dict:
    """
    Estimate calories from an image description.
    The MCP server cannot directly see images; ChatGPT should pass a visual description.
    """

    estimate = estimate_from_text_simple(image_description)

    if save and estimate.get("estimate"):
        est = estimate["estimate"]
        row = {
            "user_id": USER_ID,
            "eaten_at": iso_now(),
            "meal": meal,
            "food_name": image_description,
            "calories": int(est["calories"]),
            "protein_g": est["protein_g"],
            "carbs_g": est["carbs_g"],
            "fat_g": est["fat_g"],
            "source": "image_description_estimate",
            "confidence": estimate.get("confidence", 0.5),
            "note": "Auto-estimated from image description",
        }
        result = supabase.table("food_logs").insert(row).execute()
        estimate["saved"] = result.data

    return {
        **estimate,
        "note": "ตัวนี้รับ image_description ไม่ได้วิเคราะห์ไฟล์รูปเองโดยตรง",
    }


@mcp.tool()
def recommend_food(goal: str = "high_protein", remaining_calories: Optional[int] = None) -> dict:
    """Recommend food options based on simple goal."""

    options = {
        "high_protein": [
            {"food": "อกไก่ + ข้าว", "calories": 450, "protein_g": 45},
            {"food": "เวย์โปรตีน + กล้วย", "calories": 250, "protein_g": 25},
            {"food": "ไข่ต้ม 2 ฟอง + นมโปรตีน", "calories": 350, "protein_g": 35},
        ],
        "low_calorie": [
            {"food": "สุกี้น้ำไก่", "calories": 350, "protein_g": 30},
            {"food": "ยำอกไก่", "calories": 300, "protein_g": 35},
            {"food": "ข้าวครึ่งจาน + กับข้าวโปรตีนสูง", "calories": 400, "protein_g": 30},
        ],
        "pre_workout": [
            {"food": "กล้วย + เวย์", "calories": 230, "protein_g": 25},
            {"food": "ขนมปังโฮลวีท + ไข่", "calories": 300, "protein_g": 18},
        ],
        "post_workout": [
            {"food": "ข้าว + อกไก่", "calories": 500, "protein_g": 45},
            {"food": "นมโปรตีน + แซนวิช", "calories": 550, "protein_g": 40},
        ],
    }

    selected = options.get(goal, options["high_protein"])

    if remaining_calories:
        selected = [x for x in selected if x["calories"] <= remaining_calories] or selected

    return {
        "goal": goal,
        "remaining_calories": remaining_calories,
        "recommendations": selected,
    }


@mcp.tool()
def recommend_macros(
    weight_kg: Optional[float] = None,
    calorie_goal: Optional[int] = None,
    goal_type: str = "fat_loss",
) -> dict:
    """Recommend simple calorie and macro targets."""

    latest_weight = get_latest_weight()
    goal = get_latest_goal()

    if not weight_kg:
        if latest_weight:
            weight_kg = float(latest_weight["weight_kg"])
        elif goal and goal.get("current_weight_kg"):
            weight_kg = float(goal["current_weight_kg"])
        else:
            weight_kg = 94.0

    if not calorie_goal:
        calorie_goal = goal.get("calorie_goal") if goal and goal.get("calorie_goal") else 2200

    if goal_type == "fat_loss":
        protein_g = round(weight_kg * 1.8)
        fat_g = round(weight_kg * 0.7)
    elif goal_type == "performance":
        protein_g = round(weight_kg * 1.6)
        fat_g = round(weight_kg * 0.8)
    else:
        protein_g = round(weight_kg * 1.6)
        fat_g = round(weight_kg * 0.7)

    protein_cal = protein_g * 4
    fat_cal = fat_g * 9
    carbs_g = round(max((calorie_goal - protein_cal - fat_cal) / 4, 0))

    return {
        "weight_kg": weight_kg,
        "goal_type": goal_type,
        "calorie_goal": calorie_goal,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "note": "เป็นค่าเริ่มต้นแบบง่าย ควรปรับจากน้ำหนักจริง ความหิว การซ้อม และผลลัพธ์รายสัปดาห์",
    }


# -------------------------
# Optional: goal setup
# -------------------------

@mcp.tool()
def set_goal(
    calorie_goal: Optional[int] = None,
    protein_goal_g: Optional[float] = None,
    carbs_goal_g: Optional[float] = None,
    fat_goal_g: Optional[float] = None,
    weight_goal_kg: Optional[float] = None,
    current_weight_kg: Optional[float] = None,
    height_cm: Optional[float] = None,
    activity_level: Optional[str] = None,
    goal_type: Optional[str] = None,
    hyrox_event_date: Optional[str] = None,
) -> dict:
    """Create or update user goals."""

    existing = get_latest_goal()

    row = {
        "user_id": USER_ID,
        "calorie_goal": calorie_goal,
        "protein_goal_g": protein_goal_g,
        "carbs_goal_g": carbs_goal_g,
        "fat_goal_g": fat_goal_g,
        "weight_goal_kg": weight_goal_kg,
        "current_weight_kg": current_weight_kg,
        "height_cm": height_cm,
        "activity_level": activity_level,
        "goal_type": goal_type,
        "hyrox_event_date": hyrox_event_date,
        "updated_at": iso_now(),
    }

    clean_row = {k: v for k, v in row.items() if v is not None}

    if existing:
        result = (
            supabase.table("user_goals")
            .update(clean_row)
            .eq("user_id", USER_ID)
            .execute()
        )
    else:
        result = supabase.table("user_goals").insert(clean_row).execute()

    return {
        "status": "success",
        "goal": result.data,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")