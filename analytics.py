from flask import Blueprint, render_template, request, jsonify, make_response
from datetime import datetime, timedelta
from io import BytesIO
import pandas as pd
import plotly.express as px
import plotly.utils
import json
from main import db, Booking, User, Workplace

analytics_bp = Blueprint('analytics', __name__)


def get_booking_stats(start_date=None, end_date=None):
    """Получение статистики по бронированиям"""
    query = Booking.query.join(User).join(Workplace)

    if start_date:
        query = query.filter(Booking.start_time >= start_date)
    if end_date:
        query = query.filter(Booking.start_time <= end_date)

    bookings = query.all()
    return bookings


@analytics_bp.route('/analytics')
def analytics_dashboard():
    """Главная страница аналитики"""
    # Параметры фильтрации по дате
    default_end = datetime.now()
    default_start = default_end - timedelta(days=30)

    start_date = request.args.get('start_date', default_start.strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', default_end.strftime('%Y-%m-%d'))

    # Преобразуем даты
    start_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else default_start
    end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else default_end

    # Получаем данные
    bookings = get_booking_stats(start_dt, end_dt)

    # Подготавливаем данные для графиков
    user_stats = get_user_statistics(bookings)
    day_stats = get_day_statistics(bookings)
    department_stats = get_department_statistics(bookings)
    time_stats = get_time_statistics(bookings)

    # Создаем графики
    user_chart = create_user_chart(user_stats)
    day_chart = create_day_chart(day_stats)
    department_chart = create_department_chart(department_stats)
    time_chart = create_time_chart(time_stats)

    return render_template('analytics.html',
                           user_stats=user_stats,
                           day_stats=day_stats,
                           department_stats=department_stats,
                           time_stats=time_stats,
                           user_chart=user_chart,
                           day_chart=day_chart,
                           department_chart=department_chart,
                           time_chart=time_chart,
                           start_date=start_date,
                           end_date=end_date)


def get_user_statistics(bookings):
    """Статистика по пользователям"""
    user_data = {}
    for booking in bookings:
        username = booking.user.username
        if username not in user_data:
            user_data[username] = {
                'booking_count': 0,
                'total_hours': 0,
                'departments': set(),
                'last_booking': booking.start_time
            }

        user_data[username]['booking_count'] += 1
        duration = (booking.end_time - booking.start_time).total_seconds() / 3600
        user_data[username]['total_hours'] += duration
        user_data[username]['departments'].add(booking.workplace.department)
        user_data[username]['last_booking'] = max(user_data[username]['last_booking'], booking.start_time)

    # Преобразуем в список для сортировки
    result = []
    for username, data in user_data.items():
        result.append({
            'username': username,
            'booking_count': data['booking_count'],
            'total_hours': round(data['total_hours'], 2),
            'departments_count': len(data['departments']),
            'last_booking': data['last_booking'].strftime('%d.%m.%Y'),
            'avg_duration': round(data['total_hours'] / data['booking_count'], 2) if data['booking_count'] > 0 else 0
        })

    return sorted(result, key=lambda x: x['booking_count'], reverse=True)


def get_day_statistics(bookings):
    """Статистика по дням недели"""
    days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    day_data = {day: 0 for day in days}

    for booking in bookings:
        day_index = booking.start_time.weekday()
        day_data[days[day_index]] += 1

    return [{'day': day, 'count': count} for day, count in day_data.items()]


def get_department_statistics(bookings):
    """Статистика по отделам"""
    dept_data = {}
    for booking in bookings:
        department = booking.workplace.department
        if department not in dept_data:
            dept_data[department] = 0
        dept_data[department] += 1

    return [{'department': dept, 'count': count} for dept, count in dept_data.items()]


def get_time_statistics(bookings):
    """Статистика по времени суток"""
    hours = {f"{i:02d}:00": 0 for i in range(8, 19)}  # с 8:00 до 18:00

    for booking in bookings:
        hour = booking.start_time.hour
        if 8 <= hour < 19:
            hour_key = f"{hour:02d}:00"
            hours[hour_key] = hours.get(hour_key, 0) + 1

    return [{'hour': hour, 'count': count} for hour, count in hours.items()]


def create_user_chart(user_stats):
    """График топ пользователей по количеству бронирований"""
    if not user_stats:
        return None

    top_users = user_stats[:10]  # Топ 10 пользователей
    df = pd.DataFrame(top_users)
    fig = px.bar(df, x='username', y='booking_count',
                 title='Топ пользователей по количеству бронирований',
                 labels={'username': 'Пользователь', 'booking_count': 'Количество бронирований'})
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def create_day_chart(day_stats):
    """График популярности дней недели"""
    if not day_stats:
        return None

    df = pd.DataFrame(day_stats)
    fig = px.bar(df, x='day', y='count',
                 title='Распределение бронирований по дням недели',
                 labels={'day': 'День недели', 'count': 'Количество бронирований'})
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def create_department_chart(department_stats):
    """График популярности отделов"""
    if not department_stats:
        return None

    df = pd.DataFrame(department_stats)
    fig = px.pie(df, values='count', names='department',
                 title='Распределение бронирований по отделам')
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def create_time_chart(time_stats):
    """График популярности времени"""
    if not time_stats:
        return None

    df = pd.DataFrame(time_stats)
    fig = px.line(df, x='hour', y='count',
                  title='Распределение бронирований по времени начала',
                  labels={'hour': 'Время начала', 'count': 'Количество бронирований'})
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


@analytics_bp.route('/analytics/export')
def export_analytics():
    """Экспорт аналитики в Excel"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    start_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
    end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None

    bookings = get_booking_stats(start_dt, end_dt)

    # Создаем Excel файл в памяти
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Лист с общей статистикой
        user_stats = get_user_statistics(bookings)
        df_users = pd.DataFrame(user_stats)
        df_users.to_excel(writer, sheet_name='Статистика по пользователям', index=False)

        # Лист с днями недели
        day_stats = get_day_statistics(bookings)
        df_days = pd.DataFrame(day_stats)
        df_days.to_excel(writer, sheet_name='Статистика по дням недели', index=False)

        # Лист с отделами
        dept_stats = get_department_statistics(bookings)
        df_dept = pd.DataFrame(dept_stats)
        df_dept.to_excel(writer, sheet_name='Статистика по отделам', index=False)

        # Лист с детализацией бронирований
        booking_data = []
        for booking in bookings:
            booking_data.append({
                'Пользователь': booking.user.username,
                'Отдел': booking.workplace.department,
                'Место': booking.workplace.number,
                'Дата начала': booking.start_time.strftime('%d.%m.%Y'),
                'Время начала': booking.start_time.strftime('%H:%M'),
                'Время окончания': booking.end_time.strftime('%H:%M'),
                'День недели': ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][booking.start_time.weekday()],
                'Длительность (ч)': round((booking.end_time - booking.start_time).total_seconds() / 3600, 2)
            })

        df_bookings = pd.DataFrame(booking_data)
        df_bookings.to_excel(writer, sheet_name='Детализация бронирований', index=False)

    output.seek(0)

    # Создаем response для скачивания
    filename = f"analytics_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


# Регистрируем blueprint в main.py
def init_app(app):
    app.register_blueprint(analytics_bp)