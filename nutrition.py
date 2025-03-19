import requests
import json
import os
import time
import pandas as pd
from decimal import Decimal
from datetime import datetime, timedelta

WEIGHT_LOSS = True
ACTIVITY_LEVEL = "sedentary"
CALORIE_FLOOR = 1600
CALORIE_DEFICIT = {
    'aggressive': 750, 'medium': 500, 'low': 250
}
ACTIVITY_MULTIPLIERS = {
    'sedentary': 1.2, 'lightly_active': 1.375, 'moderately_active': 1.55,
    'very_active': 1.725, 'extra_active': 1.9
}
athlete = {'sex': 'M', 'height': '170', 'weight': '70', 'age': 33, 'bike_threshold': 162.0, 'run_threshold': 6.17, 'swim_threshold': 2.33}

def calculate_bmr(weight_kg, height_cm, age, sex):
    if sex == 'M':
        adj_factor = 5.0
    if sex == 'F':
        adj_factor = -161
    bmr = ((10*weight_kg) + (6.25*height_cm) - (5*age) + adj_factor)
    
    return bmr

def calculate_tdee(bmr, ACTIVITY_LEVEL):
    return bmr * ACTIVITY_MULTIPLIERS.get(ACTIVITY_LEVEL, 1.2)

def calculate_cho(threshold, intensity_factor, planned_hrs):
    if threshold <= 200:
        cho = 10
    elif threshold <= 240:
        cho = 11
    elif threshold <= 270:
        cho = 12
    elif threshold <= 300:
        cho = 13
    elif threshold <= 330:
        cho = 14
    elif threshold <= 360:
        cho = 15
    else:
        cho = 16
    tss = (intensity_factor**2) * 100 * planned_hrs
    cho_calories = tss * cho
    cho_grams = round(cho_calories/4)
    return cho_grams

def calculate_pro(weight_kg, planned_hours, WEIGHT_LOSS):
    if WEIGHT_LOSS:
        pro = 1
    elif planned_hours < 1:
        pro = 0.7
    elif planned_hours < 2:
        pro = 0.8
    elif planned_hours < 2.5:
        pro = 0.9
    else:
        pro = 1
    pro_grams = round((weight_kg * 2.2) * pro)
    return pro_grams

def calculate_running_expenditure(pace_min_km, duration_hours, weight_kg, economy=210):
    try:
        liters_o2_per_min = ((210/pace_min_km) * weight_kg)/1000
        kcals_per_min = liters_o2_per_min * 5
        kcals = kcals_per_min * duration_hours * 60
        return kcals
    except ZeroDivisionError:
        return 0

def calculate_cycling_expenditure(power, duration_hours, economy=75):
    liters_o2_per_min = power/75
    kcals_per_min = liters_o2_per_min * 5
    kcals = kcals_per_min * duration_hours * 60
    return kcals

#Rough estimate for swimming calorie expenditure
def calculate_swim_expenditure(duration_hours):
    kcals = (duration_hours * 60) * 10
    return kcals

def generate_nutrition_plan(athlete, workouts):
    bmr = calculate_bmr(athlete['weight'], athlete['height'], athlete['age'], athlete['sex'])
    tdee = calculate_tdee(bmr, ACTIVITY_LEVEL)
    iee = tdee - CALORIE_DEFICIT.get("medium") if WEIGHT_LOSS else tdee

    nutrition_plan = {}
    
    # Group workouts by day
    workouts_by_day = {}
    for workout in workouts:
        day = workout['workoutDay'].split('T')[0]
        if day not in workouts_by_day:
            workouts_by_day[day] = []
        workouts_by_day[day].append(workout)

    # Process workouts per day    
    for day, daily_workouts in workouts_by_day.items():
        workout_totals = {
            "Bike": {"sessions": 0, "power": 0, "hours": 0},
            "Run": {"sessions": 0, "pace": 0, "hours": 0},
            "Swim": {"sessions": 0, "pace": 0, "hours": 0},
        }

        workouts = []
        
        for workout in daily_workouts:
            total_time = workout.get('total_time', 0)
            
            workout_type = {1: "Swim", 2: "Bike", 3: "Run", 7: "Rest"}.get(workout.get('workout_typeValueId'))
            if workout_type is None:
                print("Unsupported workout type")
                continue

            workouts.append(workout_type)

            if workout_type == "Rest":
                continue
            
            if 'ifPlanned' in workout and workout['ifPlanned'] is not None:
                if workout_type == "Run":
                    workout_totals["Run"]["pace"] += athlete['run_threshold'] / workout['ifPlanned']
                    workout_totals["Run"]["hours"] += total_time
                    workout_totals["Run"]["sessions"] += 1
                elif workout_type == "Bike":
                    workout_totals["Bike"]["power"] += workout['ifPlanned'] * athlete['bike_threshold']
                    workout_totals["Bike"]["hours"] += total_time
                    workout_totals["Bike"]["sessions"] += 1
                elif workout_type == "Swim":
                    workout_totals["Swim"]["pace"] += athlete['swim_threshold'] / workout['ifPlanned']
                    workout_totals["Swim"]["hours"] += total_time
                    workout_totals["Swim"]["sessions"] += 1
            elif workout_type == "Swim": 
                distance_planned = workout.get('distancePlanned', 0)
                if distance_planned:
                    workout_totals["Swim"]["hours"] += ((distance_planned / 100) * athlete['swim_threshold']) / 60
                    workout_totals["Swim"]["pace"] += athlete['swim_threshold'] * 0.8
                    workout_totals["Swim"]["sessions"] += 1
                elif total_time:
                    workout_totals["Swim"]["hours"] += total_time
                    workout_totals["Swim"]["pace"] += athlete['swim_threshold'] * 0.8
                    workout_totals["Swim"]["sessions"] += 1
            else:
                targets = [
                    target
                    for step in workout['structure']['structure']
                    for s in step['steps']
                    for target in s.get('targets', [])
                ]
                df = pd.DataFrame(targets)
                df['average'] = df[['minValue', 'maxValue']].mean(axis=1)
                overall_average = df['average'].mean() / 100

                if workout_type == "Run":
                    workout_totals["Run"]["pace"] += (athlete['run_threshold'] / overall_average) * total_time
                    workout_totals["Run"]["hours"] += total_time
                elif workout_type == "Bike":
                    workout_totals["Bike"]["power"] += (athlete['bike_threshold'] * overall_average) * total_time
                    workout_totals["Bike"]["hours"] += total_time

        # Calculate weighted averages
        bike_power = (workout_totals["Bike"]["power"] / workout_totals["Bike"]["sessions"]) if workout_totals["Bike"]["hours"] else 0
        run_pace = (workout_totals["Run"]["pace"] / workout_totals["Run"]["sessions"]) if workout_totals["Run"]["hours"] else 0
        swim_pace = (workout_totals["Swim"]["pace"] / workout_totals["Swim"]["sessions"]) if workout_totals["Swim"]["hours"] else 0
        
        bike_hrs = workout_totals["Bike"]["hours"]
        run_hrs = workout_totals["Run"]["hours"]
        swim_hrs = workout_totals["Swim"]["hours"] 

        # Energy expenditure calculations
        bike_kcal = calculate_cycling_expenditure(bike_power, bike_hrs) if bike_hrs else 0
        run_kcal = calculate_running_expenditure(run_pace, run_hrs, athlete['weight']) if run_hrs else 0
        swim_kcal = calculate_swim_expenditure(swim_hrs) if swim_hrs else 0

        total_kcal = iee + bike_kcal + run_kcal + swim_kcal
        total_kcal = max(total_kcal, CALORIE_FLOOR)  # Ensure calorie floor isn't breached

        bike_intensity_factor = bike_power / athlete['bike_threshold'] if bike_hrs else 0
        run_intensity_factor = athlete['run_threshold'] / run_pace if run_hrs else 0
        swim_intensity_factor = athlete['swim_threshold'] / swim_pace if swim_hrs else 0         
        
        total_hrs = bike_hrs + run_hrs + swim_hrs
        
        if total_hrs == 0:
            cho = 50
        else:
            average_intensity_factor = ((bike_intensity_factor * bike_hrs) + (run_intensity_factor * run_hrs) + (swim_intensity_factor * swim_hrs)) / (bike_hrs + run_hrs + swim_hrs)
            cho = calculate_cho(athlete['bike_threshold'], average_intensity_factor, total_hrs)
        
        pro = calculate_pro(athlete['weight'], total_hrs, WEIGHT_LOSS)
        fat = round((total_kcal - (cho * 4) - (pro * 4)) / 9)
        
        nutrition_plan[day] = {'Workouts': workouts,'Total Calories': round(total_kcal), 'CHO': cho, 'Protein': pro, 'Fat': fat}

    return nutrition_plan

def main():
    workouts = [] #Pass your TP workouts into here
    generate_nutrition_plan(athlete, workouts)

if __name__ == "__main__":
    main()