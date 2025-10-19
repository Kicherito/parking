from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
import re
import pandas as pd
import plotly.express as px
import plotly.utils
import json
from io import BytesIO

app = Flask(__name__, template_folder='/root/parking/templates')
app.secret_key = 'super_secret_key_12345'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Конфигурация PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:Valet!2@localhost/office_booking_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# Модели БД
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    default_location = db.Column(db.String(100), nullable=True)
    has_default_location = db.Column(db.Boolean, default=False)
    bookings = db.relationship('Booking', backref='user', lazy=True)


class Workplace(db.Model):
    __tablename__ = 'workplaces'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, nullable=False)
    location = db.Column(db.String(100), nullable=False)
    bookings = db.relationship('Booking', backref='workplace', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('number', 'location', name='workplaces_number_location_key'),
    )


class Booking(db.Model):
    __tablename__ = 'bookings'
    id = db.Column(db.Integer, primary_key=True)
    place_id = db.Column(db.Integer, db.ForeignKey('workplaces.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserManager:
    def __init__(self):
        self.current_user = None

    def register(self, username: str, password: str) -> bool:
        if User.query.filter_by(username=username).first():
            return False
        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()
        return True

    def login(self, username: str, password: str) -> bool:
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            self.current_user = username
            session['username'] = username
            session['default_location'] = user.default_location
            session['has_default_location'] = user.has_default_location
            return True
        return False

    def logout(self):
        self.current_user = None
        session.pop('username', None)
        session.pop('default_location', None)
        session.pop('has_default_location', None)

    def is_authenticated(self) -> bool:
        return self.current_user is not None

    def set_default_location(self, username: str, location: str, save_as_default: bool) -> bool:
        user = User.query.filter_by(username=username).first()
        if user:
            if save_as_default:
                user.default_location = location
                user.has_default_location = True
            else:
                user.default_location = None
                user.has_default_location = False

            db.session.commit()
            session['default_location'] = user.default_location
            session['has_default_location'] = user.has_default_location
            return True
        return False

    def change_password(self, username: str, current_password: str, new_password: str) -> bool:
        """Изменение пароля пользователя"""
        user = User.query.filter_by(username=username, password=current_password).first()
        if user:
            user.password = new_password
            db.session.commit()
            return True
        return False

    def get_user_stats(self, username: str):
        """Получить статистику пользователя"""
        user_obj = User.query.filter_by(username=username).first()
        if not user_obj:
            return None

        # Общее количество бронирований
        total_bookings = Booking.query.filter_by(user_id=user_obj.id).count()

        # Активные бронирования
        active_bookings = Booking.query.filter(
            Booking.user_id == user_obj.id,
            Booking.end_time > datetime.now()
        ).count()

        # Завершенные бронирования
        completed_bookings = Booking.query.filter(
            Booking.user_id == user_obj.id,
            Booking.end_time <= datetime.now()
        ).count()

        # Первое бронирование
        first_booking = Booking.query.filter_by(user_id=user_obj.id).order_by(Booking.start_time.asc()).first()
        first_booking_date = first_booking.start_time.strftime('%d.%m.%Y') if first_booking else 'Нет'

        # Самая популярная локация
        from sqlalchemy import func
        popular_location = db.session.query(
            Workplace.location,
            func.count(Booking.id).label('count')
        ).join(Booking).filter(
            Booking.user_id == user_obj.id
        ).group_by(Workplace.location).order_by(func.count(Booking.id).desc()).first()

        # Статистика по месяцам
        monthly_stats = db.session.query(
            db.func.extract('month', Booking.start_time).label('month'),
            db.func.count(Booking.id).label('count')
        ).filter(
            Booking.user_id == user_obj.id,
            Booking.start_time >= datetime.now() - timedelta(days=365)
        ).group_by('month').all()

        monthly_data = {int(month): count for month, count in monthly_stats}

        return {
            'total_bookings': total_bookings,
            'active_bookings': active_bookings,
            'completed_bookings': completed_bookings,
            'first_booking_date': first_booking_date,
            'popular_location': popular_location[0] if popular_location else 'Нет',
            'member_since': user_obj.id,
            'monthly_stats': monthly_data
        }


class OfficeBookingSystem:
    def __init__(self):
        self.working_hours = (8, 18)

    def is_available(self, place_id: int, start: datetime, end: datetime) -> bool:
        # Убрана проверка рабочего времени - разрешаем бронирование в любое время
        overlapping_bookings = Booking.query.filter(
            Booking.place_id == place_id,
            Booking.start_time < end,
            Booking.end_time > start
        ).count()

        return overlapping_bookings == 0

    def book_place(self, place_id: int, user: str, dates: list, start_time: str, end_time: str) -> list:
        results = []
        workplace = Workplace.query.get(place_id)
        if not workplace:
            return [("error", "Неверный ID места")]

        user_obj = User.query.filter_by(username=user).first()
        if not user_obj:
            return [("error", "Пользователь не найден")]

        for date_str in dates:
            try:
                start_dt = datetime.fromisoformat(f"{date_str}T{start_time}")
                end_dt = datetime.fromisoformat(f"{date_str}T{end_time}")
            except ValueError:
                results.append(("error", f"Неверный формат даты: {date_str}"))
                continue

            # Проверка максимальной длительности (7 дней)
            if (end_dt - start_dt) > timedelta(days=7):
                results.append(("error", "Максимальный срок бронирования - 7 дней"))
                continue

            # Проверка что бронирование не более чем на 30 дней вперед
            max_future_date = datetime.now() + timedelta(days=30)
            if start_dt > max_future_date:
                results.append(("error", "Бронирование возможно максимум на 30 дней вперед"))
                continue

            # Проверка доступности места
            if not self.is_available(place_id, start_dt, end_dt):
                results.append(("error", f"Место {workplace.number} занято на {date_str}"))
                continue

            # Добавляем бронирование
            new_booking = Booking(
                place_id=place_id,
                user_id=user_obj.id,
                start_time=start_dt,
                end_time=end_dt
            )
            db.session.add(new_booking)
            results.append(("success", f"Место {workplace.number} забронировано на {date_str}"))

        db.session.commit()
        return results

    def cancel_booking(self, booking_id: int) -> str:
        booking = Booking.query.get(booking_id)
        if not booking:
            return "Бронирование не найдено"

        if booking.user.username != session.get('username'):
            return "Вы не можете отменить чужое бронирование"

        db.session.delete(booking)
        db.session.commit()
        return "Бронирование успешно отменено"

    def cancel_all_bookings(self, user: str):
        """Отмена всех бронирований пользователя"""
        user_obj = User.query.filter_by(username=user).first()
        if not user_obj:
            return "Пользователь не найден"

        # Получаем все будущие бронирования пользователя
        bookings = Booking.query.filter(
            Booking.user_id == user_obj.id,
            Booking.end_time > datetime.now()
        ).all()

        if not bookings:
            return "Нет активных бронирований для отмены"

        # Удаляем все бронирования
        for booking in bookings:
            db.session.delete(booking)

        db.session.commit()
        return f"Все бронирования успешно отменены ({len(bookings)} шт.)"

    def cancel_bookings_in_range(self, user: str, start_date: str, end_date: str):
        """Отмена бронирований пользователя в указанном диапазоне дат"""
        user_obj = User.query.filter_by(username=user).first()
        if not user_obj:
            return "Пользователь не найден"

        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)  # включая конечную дату
        except ValueError:
            return "Неверный формат даты"

        # Получаем бронирования в указанном диапазоне
        bookings = Booking.query.filter(
            Booking.user_id == user_obj.id,
            Booking.start_time >= start_dt,
            Booking.start_time < end_dt
        ).all()

        if not bookings:
            return "Нет бронирований в указанном диапазоне"

        # Удаляем бронирования
        for booking in bookings:
            db.session.delete(booking)

        db.session.commit()
        return f"Бронирования в диапазоне {start_date} - {end_date} отменены ({len(bookings)} шт.)"

    def show_user_bookings(self, user: str, start_date=None, end_date=None):
        user_obj = User.query.filter_by(username=user).first()
        if not user_obj:
            return []

        # Базовый запрос - только будущие бронирования
        query = db.session.query(Booking, Workplace).join(Workplace).filter(
            Booking.user_id == user_obj.id,
            Booking.end_time > datetime.now()  # только будущие брони
        )

        # Фильтрация по диапазону дат
        if start_date and end_date:
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)  # включая конечную дату
                query = query.filter(Booking.start_time >= start_dt, Booking.start_time < end_dt)
            except ValueError:
                pass
        elif start_date:
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(Booking.start_time >= start_dt)
            except ValueError:
                pass
        elif end_date:
            try:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(Booking.start_time < end_dt)
            except ValueError:
                pass

        # Сортировка по дате начала (сначала ближайшие)
        query = query.order_by(Booking.start_time.asc())

        results = query.all()

        user_bookings = []
        for booking, workplace in results:
            user_bookings.append({
                'id': booking.id,
                'place': workplace.number,
                'location': workplace.location,
                'start': booking.start_time.isoformat(),
                'end': booking.end_time.isoformat(),
                'start_dt': booking.start_time,
                'end_dt': booking.end_time,
                'status': 'active'  # теперь все брони активные (будущие)
            })
        return user_bookings

    def get_available_places(self, location: str, dates: list, start_time: str, end_time: str) -> list:
        available_places = []

        # Получаем все места в локации
        workplaces = Workplace.query.filter_by(location=location).order_by(Workplace.number).all()

        for workplace in workplaces:
            is_available_for_all_dates = True

            for date_str in dates:
                try:
                    start_dt = datetime.fromisoformat(f"{date_str}T{start_time}")
                    end_dt = datetime.fromisoformat(f"{date_str}T{end_time}")
                except ValueError:
                    is_available_for_all_dates = False
                    break

                if not self.is_available(workplace.id, start_dt, end_dt):
                    is_available_for_all_dates = False
                    break

            available_places.append({
                'id': workplace.id,
                'number': workplace.number,
                'available': is_available_for_all_dates
            })

        return available_places

    def get_locations(self):
        # Получаем уникальные локации из базы данных
        locations = db.session.query(Workplace.location).distinct().all()
        return [loc[0] for loc in locations]

    def get_location_places_count(self):
        # Получаем количество мест для каждой локации
        locations = self.get_locations()
        location_places = {}
        for location in locations:
            count = Workplace.query.filter_by(location=location).count()
            location_places[location] = count
        return location_places

    def get_nearest_booking_info(self, user: str):
        """Получить информацию о ближайшем бронировании пользователя"""
        user_obj = User.query.filter_by(username=user).first()
        if not user_obj:
            return None

        # Ищем ближайшее активное бронирование
        now = datetime.now()
        nearest_booking = Booking.query.join(Workplace).filter(
            Booking.user_id == user_obj.id,
            Booking.end_time > now
        ).order_by(Booking.start_time.asc()).first()

        if nearest_booking:
            return {
                'date': nearest_booking.start_time.strftime('%d.%m.%Y'),
                'time': nearest_booking.start_time.strftime('%H:%M'),
                'place': nearest_booking.workplace.number,
                'location': nearest_booking.workplace.location
            }
        return None


# Инициализация систем
user_manager = UserManager()
booking_system = OfficeBookingSystem()


# Функции для аналитики
def get_booking_stats(start_date=None, end_date=None, location=None):
    """Получение статистики по бронированиям с корректной фильтрацией по датам"""
    query = Booking.query.join(User).join(Workplace)

    if start_date:
        # Устанавливаем время начала на 00:00:00 для включения всех броней с этой даты
        start_datetime = datetime.combine(start_date, datetime.min.time())
        query = query.filter(Booking.start_time >= start_datetime)
    if end_date:
        # Устанавливаем время окончания на 23:59:59 для включения всех броней по эту дату
        end_datetime = datetime.combine(end_date, datetime.max.time())
        query = query.filter(Booking.start_time <= end_datetime)
    if location:
        query = query.filter(Workplace.location == location)

    bookings = query.all()
    return bookings


def get_occupancy_percentage(start_date=None, end_date=None, location=None):
    """Расчет процента занятости как отношение всех броней к общему количеству возможных бронирований"""

    # Получаем общее количество мест (всех или в конкретной локации)
    if location:
        total_places = Workplace.query.filter_by(location=location).count()
    else:
        total_places = Workplace.query.count()

    if total_places == 0:
        return 0

    # Рассчитываем количество дней в периоде
    if start_date and end_date:
        # Учитываем, что оба дня включены в период
        days_count = (end_date - start_date).days + 1
    else:
        # Если даты не указаны, используем период по умолчанию (30 дней)
        days_count = 30

    # Общее количество возможных броней = количество мест × количество дней
    total_possible_bookings = total_places * days_count

    if total_possible_bookings == 0:
        return 0

    # Получаем ВСЕ бронирования за период (не только уникальные места)
    query = Booking.query.join(Workplace)

    if start_date:
        start_datetime = datetime.combine(start_date, datetime.min.time())
        query = query.filter(Booking.start_time >= start_datetime)
    if end_date:
        end_datetime = datetime.combine(end_date, datetime.max.time())
        query = query.filter(Booking.start_time <= end_datetime)
    if location:
        query = query.filter(Workplace.location == location)

    # Считаем общее количество бронирований
    total_actual_bookings = query.count()

    # Рассчитываем процент занятости
    percentage = (total_actual_bookings / total_possible_bookings) * 100
    return round(percentage, 2)


def get_user_statistics(bookings):
    """Статистика по пользователям"""
    user_data = {}
    for booking in bookings:
        username = booking.user.username
        if username not in user_data:
            user_data[username] = {
                'booking_count': 0,
                'total_hours': 0,
                'last_booking': booking.start_time
            }

        user_data[username]['booking_count'] += 1
        duration = (booking.end_time - booking.start_time).total_seconds() / 3600
        user_data[username]['total_hours'] += duration
        user_data[username]['last_booking'] = max(user_data[username]['last_booking'], booking.start_time)

    # Преобразуем в список для сортировки
    result = []
    for username, data in user_data.items():
        result.append({
            'username': username,
            'booking_count': data['booking_count'],
            'total_hours': round(data['total_hours'], 2),
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


def get_location_statistics(bookings, all_locations):
    """Статистика по локациям - всегда показывает все локации, даже с нулевыми бронированиями"""
    loc_data = {}

    # Инициализируем все локации с нулевыми значениями
    for location in all_locations:
        loc_data[location] = 0

    # Заполняем реальными данными
    for booking in bookings:
        location = booking.workplace.location
        if location in loc_data:
            loc_data[location] += 1
        else:
            # На случай, если есть бронирование с локацией, которой нет в all_locations
            loc_data[location] = 1

    return [{'location': loc, 'count': count} for loc, count in loc_data.items()]


def get_time_statistics(bookings):
    """Статистика по времени суток"""
    hours = {f"{i:02d}:00": 0 for i in range(8, 19)}  # с 8:00 до 18:00

    for booking in bookings:
        hour = booking.start_time.hour
        if 8 <= hour < 19:
            hour_key = f"{hour:02d}:00"
            hours[hour_key] = hours.get(hour_key, 0) + 1

    return [{'hour': hour, 'count': count} for hour, count in hours.items()]


# Маршруты Flask
@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if user_manager.login(username, password):
            flash('Вход выполнен успешно!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Неверное имя пользователя или пароль', 'error')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if not all(key in request.form for key in ['username', 'password', 'confirm_password']):
            flash('Все поля обязательны для заполнения', 'error')
            return render_template('register.html')

        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Пароли не совпадают', 'error')
        elif user_manager.register(username, password):
            flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Имя пользователя уже занято', 'error')

    return render_template('register.html')


@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))

    user_obj = User.query.filter_by(username=session['username']).first()
    default_location = user_obj.default_location if user_obj and user_obj.has_default_location else None
    has_default_location = user_obj.has_default_location if user_obj else False

    # Получаем параметры фильтрации
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    user_bookings = booking_system.show_user_bookings(session['username'], start_date=start_date, end_date=end_date)
    locations = booking_system.get_locations()
    location_places = booking_system.get_location_places_count()

    # Получаем информацию о ближайшем бронировании
    nearest_booking_info = booking_system.get_nearest_booking_info(session['username'])

    return render_template(
        'dashboard.html',
        username=session['username'],
        bookings=user_bookings,
        locations=locations,
        default_location=default_location,
        has_default_location=has_default_location,
        working_hours=booking_system.working_hours,
        today=datetime.now().strftime('%d.%m.%Y'),
        min_date=datetime.now().strftime('%Y-%m-%d'),
        max_date=(datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
        now=datetime.now(),
        start_date=start_date,
        end_date=end_date,
        location_places=location_places,
        nearest_booking_info=nearest_booking_info
    )


@app.route('/get_available_places', methods=['POST'])
def get_available_places():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    location = data.get('location')
    dates = data.get('dates', [])
    start_time = data.get('start_time')
    end_time = data.get('end_time')

    if not location or not dates or not start_time or not end_time:
        return jsonify({'error': 'Missing parameters'}), 400

    available_places = booking_system.get_available_places(location, dates, start_time, end_time)
    return jsonify({'available_places': available_places})


@app.route('/book', methods=['POST'])
def book():
    if 'username' not in session:
        return redirect(url_for('login'))

    place_id = int(request.form['place_id'])
    dates_str = request.form.get('dates', '')
    dates = dates_str.split(',') if dates_str else []
    start_time = request.form['start_time']
    end_time = request.form['end_time']

    results = booking_system.book_place(place_id, session['username'], dates, start_time, end_time)

    for result_type, message in results:
        flash(message, result_type)

    return redirect(url_for('dashboard'))


@app.route('/cancel/<int:booking_id>')
def cancel(booking_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    result = booking_system.cancel_booking(booking_id)
    flash(result, 'success' if 'успешно' in result else 'error')

    return redirect(url_for('dashboard'))


@app.route('/cancel_all_bookings', methods=['POST'])
def cancel_all_bookings():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    result = booking_system.cancel_all_bookings(session['username'])
    flash(result, 'success' if 'успешно'in
    result else 'error')
    return redirect(url_for('dashboard'))


@app.route('/cancel_bookings_in_range', methods=['POST'])
def cancel_bookings_in_range():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')

    if not start_date or not end_date:
        flash('Укажите начальную и конечную дату диапазона', 'error')
        return redirect(url_for('dashboard'))

    result = booking_system.cancel_bookings_in_range(session['username'], start_date, end_date)
    flash(result, 'success' if 'успешно' in result else 'error')
    return redirect(url_for('dashboard'))


@app.route('/schedule')
def schedule():
    selected_date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    view_type = request.args.get('view', 'week')
    location_filter = request.args.get('location', 'all')

    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = datetime.now().date()

    if view_type == 'week':
        days_delta = 7
    else:
        days_delta = 1

    previous_date = selected_date - timedelta(days=days_delta)
    next_date = selected_date + timedelta(days=days_delta)

    query = db.session.query(Booking, Workplace, User).join(Workplace).join(User)

    if location_filter != 'all':
        query = query.filter(Workplace.location == location_filter)

    bookings_data = query.order_by(Booking.start_time).all()

    schedule_data = {}
    for booking, workplace, user in bookings_data:
        date_str = booking.start_time.date().isoformat()
        if date_str not in schedule_data:
            schedule_data[date_str] = {}

        place_key = f"{workplace.location} - {workplace.number}"
        schedule_data[date_str][place_key] = {
            'user': user.username,
            'start': booking.start_time.time().isoformat(),
            'end': booking.end_time.time().isoformat(),
            'location': workplace.location
        }

    if view_type == 'week':
        start_of_week = selected_date - timedelta(days=selected_date.weekday())
        week_days = []
        for i in range(7):
            day = start_of_week + timedelta(days=i)
            day_str = day.isoformat()
            day_schedule = schedule_data.get(day_str, {})
            week_days.append({
                'date': day,
                'schedule': day_schedule
            })
    else:
        week_days = None

    locations = booking_system.get_locations()
    location_places = booking_system.get_location_places_count()

    return render_template('schedule.html',
                           schedule=schedule_data,
                           selected_date=selected_date,
                           formatted_date=selected_date.strftime('%d.%m.%Y'),
                           previous_date=previous_date,
                           next_date=next_date,
                           view_type=view_type,
                           working_hours=booking_system.working_hours,
                           week_days=week_days,
                           min_date=datetime.now().strftime('%Y-%m-%d'),
                           max_date=(datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
                           locations=locations,
                           location_filter=location_filter,
                           location_places=location_places)


@app.route('/save_default_location', methods=['POST'])
def save_default_location():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    location = data.get('location')
    save_as_default = data.get('save_as_default', False)

    if not location and save_as_default:
        return jsonify({'error': 'Missing location parameter'}), 400

    if user_manager.set_default_location(session['username'], location, save_as_default):
        if save_as_default:
            return jsonify({'success': True, 'message': 'Локация сохранена по умолчанию'})
        else:
            return jsonify({'success': True, 'message': 'Локация по умолчанию удалена'})

    return jsonify({'error': 'Failed to save default location'}), 400


@app.route('/profile')
def profile():
    if 'username' not in session:
        return redirect(url_for('login'))

    user_obj = User.query.filter_by(username=session['username']).first()
    user_stats = user_manager.get_user_stats(session['username'])
    locations = booking_system.get_locations()

    return render_template(
        'profile.html',
        username=session['username'],
        default_location=user_obj.default_location if user_obj else None,
        has_default_location=user_obj.has_default_location if user_obj else False,
        user_stats=user_stats,
        locations=locations
    )


@app.route('/update_default_location', methods=['POST'])
def update_default_location():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    location = data.get('location')

    user = User.query.filter_by(username=session['username']).first()
    if user:
        user.default_location = location
        user.has_default_location = bool(location)
        db.session.commit()
        session['default_location'] = location
        session['has_default_location'] = bool(location)

        return jsonify({'success': True, 'message': 'Локация по умолчанию обновлена'})

    return jsonify({'error': 'Пользователь не найден'}), 400


@app.route('/change_password', methods=['POST'])
def change_password():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')

    if not all([current_password, new_password, confirm_password]):
        return jsonify({'error': 'Все поля обязательны для заполнения'}), 400

    if new_password != confirm_password:
        return jsonify({'error': 'Новые пароли не совпадают'}), 400

    if len(new_password) < 4:
        return jsonify({'error': 'Пароль должен содержать минимум 4 символа'}), 400

    if user_manager.change_password(session['username'], current_password, new_password):
        return jsonify({'success': True, 'message': 'Пароль успешно изменен'})
    else:
        return jsonify({'error': 'Текущий пароль неверен'}), 400


@app.route('/logout', methods=['POST'])
def logout():
    user_manager.logout()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('login'))


@app.route('/analytics')
def analytics_dashboard():
    """Главная страница аналитики"""
    if 'username' not in session:
        return redirect(url_for('login'))

    # Получаем параметры фильтрации
    default_end = datetime.now()
    default_start = default_end - timedelta(days=30)

    start_date = request.args.get('start_date', default_start.strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', default_end.strftime('%Y-%m-%d'))
    location_filter = request.args.get('location', '')

    # Если пользователь явно выбрал "Все локации" (пустая строка), не используем локацию по умолчанию
    if location_filter == '':
        pass
    elif not location_filter and session.get('default_location'):
        location_filter = session['default_location']

    # Преобразуем даты в datetime объекты для корректного расчета
    start_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else default_start
    end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else default_end

    # Преобразуем в date для передачи в функции
    start_dt_date = start_dt.date()
    end_dt_date = end_dt.date()

    # Получаем данные с учетом фильтра по локации
    bookings_with_filter = get_booking_stats(start_dt_date, end_dt_date, location_filter)

    # Получаем данные БЕЗ фильтра по локации (для статистики по локациям)
    bookings_all_locations = get_booking_stats(start_dt_date, end_dt_date, None)

    # Рассчитываем процент занятости для выбранной локации (или общего)
    occupancy_percentage = get_occupancy_percentage(start_dt_date, end_dt_date, location_filter)

    # Получаем количество мест для каждой локации
    location_places = {}
    for location in booking_system.get_locations():
        location_places[location] = Workplace.query.filter_by(location=location).count()

    # Подготавливаем данные для статистики
    user_stats = get_user_statistics(bookings_with_filter)
    day_stats = get_day_statistics(bookings_with_filter)

    # Для статистики по локациям используем ВСЕ бронирования и ВСЕ локации
    locations = booking_system.get_locations()
    location_stats = get_location_statistics(bookings_all_locations, locations)

    time_stats = get_time_statistics(bookings_with_filter)

    # Получаем информацию о пользователе для чекбокса
    user_obj = User.query.filter_by(username=session['username']).first()
    has_default_location = user_obj.has_default_location if user_obj else False
    default_location = user_obj.default_location if user_obj else None

    return render_template('analytics.html',
                           user_stats=user_stats,
                           day_stats=day_stats,
                           location_stats=location_stats,
                           time_stats=time_stats,
                           start_date=start_date,
                           end_date=end_date,
                           start_dt=start_dt_date,  # Передаем как date объект
                           end_dt=end_dt_date,  # Передаем как date объект
                           locations=locations,
                           location_filter=location_filter,
                           occupancy_percentage=occupancy_percentage,
                           total_bookings=len(bookings_with_filter),
                           total_bookings_all=len(bookings_all_locations),
                           location_places=location_places,
                           has_default_location=has_default_location,
                           default_location=default_location)


@app.route('/analytics/export')
def export_analytics():
    """Экспорт аналитики в Excel"""
    if 'username' not in session:
        return redirect(url_for('login'))

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    location_filter = request.args.get('location', '')

    start_dt = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None

    bookings = get_booking_stats(start_dt, end_dt, location_filter)

    # Создаем Excel файл в памяти
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:

        # Лист с пользователями - русские заголовки
        user_stats = get_user_statistics(bookings)
        df_users = pd.DataFrame(user_stats)
        # Переименовываем столбцы на русский
        df_users = df_users.rename(columns={
            'username': 'Пользователь',
            'booking_count': 'Количество бронирований',
            'total_hours': 'Всего часов',
            'avg_duration': 'Средняя длительность',
            'last_booking': 'Последнее бронирование'
        })
        df_users.to_excel(writer, sheet_name='Статистика по пользователям', index=False)

        # Лист с дням недели
        day_stats = get_day_statistics(bookings)
        df_days = pd.DataFrame(day_stats)
        df_days = df_days.rename(columns={
            'day': 'День недели',
            'count': 'Количество бронирований'
        })
        df_days.to_excel(writer, sheet_name='Статистика по дням недели', index=False)

        # Лист с локациями
        loc_stats = get_location_statistics(bookings, booking_system.get_locations())
        df_loc = pd.DataFrame(loc_stats)
        df_loc = df_loc.rename(columns={
            'location': 'Локация',
            'count': 'Количество бронирований'
        })
        df_loc.to_excel(writer, sheet_name='Статистика по локациям', index=False)

        # Детализация бронирований
        booking_data = []
        for booking in bookings:
            booking_data.append({
                'Пользователь': booking.user.username,
                'Локация': booking.workplace.location,
                'Место': booking.workplace.number,
                'Дата начала': booking.start_time.strftime('%d.%m.%Y'),
                'Время начала': booking.start_time.strftime('%H:%M'),
                'Время окончания': booking.end_time.strftime('%H:%M'),
                'День недели': ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][booking.start_time.weekday()],
                'Длительность (ч)': round((booking.end_time - booking.start_time).total_seconds() / 3600, 2)
            })

        df_bookings = pd.DataFrame(booking_data)
        df_bookings.to_excel(writer, sheet_name='Детализация бронирований', index=False)

        # Настраиваем ширину столбцов для лучшего отображения
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            worksheet.set_column('A:Z', 15)  # Ширина всех столбцов

    output.seek(0)

    filename = f"analytics_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


# Добавляем функцию в контекст всех шаблонов
@app.context_processor
def utility_processor():
    return dict(get_occupancy_percentage=get_occupancy_percentage)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    app.run(host='0.0.0.0', port=5000, debug=True)
