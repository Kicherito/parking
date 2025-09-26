from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
import re

app = Flask(__name__, template_folder='/root/parking/templates')
app.secret_key = 'super_secret_key_12345'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Конфигурация PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:Valet12@localhost/office_booking_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)



# Модели БД
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    default_department = db.Column(db.String(100), nullable=True)
    has_default_department = db.Column(db.Boolean, default=False)
    bookings = db.relationship('Booking', backref='user', lazy=True)


class Workplace(db.Model):
    __tablename__ = 'workplaces'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    bookings = db.relationship('Booking', backref='workplace', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('number', 'department', name='workplaces_number_department_key'),
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
            session['default_department'] = user.default_department
            session['has_default_department'] = user.has_default_department
            return True
        return False

    def logout(self):
        self.current_user = None
        session.pop('username', None)
        session.pop('default_department', None)
        session.pop('has_default_department', None)

    def is_authenticated(self) -> bool:
        return self.current_user is not None

    def set_default_department(self, username: str, department: str, save_as_default: bool) -> bool:
        user = User.query.filter_by(username=username).first()
        if user:
            if save_as_default:
                user.default_department = department
                user.has_default_department = True
            else:
                user.default_department = None
                user.has_default_department = False

            db.session.commit()
            session['default_department'] = user.default_department
            session['has_default_department'] = user.has_default_department
            return True
        return False


class OfficeBookingSystem:
    def __init__(self):
        self.working_hours = (8, 18)

    def is_available(self, place_id: int, start: datetime, end: datetime) -> bool:
        if not (self.working_hours[0] <= start.hour < self.working_hours[1] and
                self.working_hours[0] < end.hour <= self.working_hours[1]):
            return False

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

    def show_user_bookings(self, user: str, filter_date=None):
        user_obj = User.query.filter_by(username=user).first()
        if not user_obj:
            return []

        # Базовый запрос
        query = db.session.query(Booking, Workplace).join(Workplace).filter(Booking.user_id == user_obj.id)

        # Фильтрация по дате
        if filter_date:
            try:
                filter_date_obj = datetime.strptime(filter_date, '%Y-%m-%d').date()
                query = query.filter(db.func.date(Booking.start_time) == filter_date_obj)
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
                'department': workplace.department,
                'start': booking.start_time.isoformat(),
                'end': booking.end_time.isoformat(),
                'start_dt': booking.start_time,
                'end_dt': booking.end_time,
                'status': 'active' if booking.end_time > datetime.now() else 'completed'
            })
        return user_bookings

    def get_available_places(self, department: str, dates: list, start_time: str, end_time: str) -> list:
        available_places = []

        # Получаем все места в отделе
        workplaces = Workplace.query.filter_by(department=department).order_by(Workplace.number).all()

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

    def get_departments(self):
        # Получаем уникальные отделы из базы данных
        departments = db.session.query(Workplace.department).distinct().all()
        return [dept[0] for dept in departments]


# Инициализация систем
user_manager = UserManager()
booking_system = OfficeBookingSystem()


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
        # Проверяем наличие всех необходимых полей в запросе
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

    # Получаем пользователя и его отдел по умолчанию
    user_obj = User.query.filter_by(username=session['username']).first()
    default_department = user_obj.default_department if user_obj and user_obj.has_default_department else None
    has_default_department = user_obj.has_default_department if user_obj else False

    # Получаем параметр фильтрации по дате
    filter_date = request.args.get('filter_date')

    user_bookings = booking_system.show_user_bookings(
        session['username'],
        filter_date=filter_date
    )

    # Получаем список отделов
    departments = booking_system.get_departments()

    # Добавляем передачу working_hours и других переменных в шаблон
    return render_template(
        'dashboard.html',
        username=session['username'],
        bookings=user_bookings,
        departments=departments,
        default_department=default_department,
        has_default_department=has_default_department,
        working_hours=booking_system.working_hours,
        today=datetime.now().strftime('%d.%m.%Y'),
        min_date=datetime.now().strftime('%Y-%m-%d'),
        max_date=(datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
        now=datetime.now(),
        filter_date=filter_date
    )


@app.route('/get_available_places', methods=['POST'])
def get_available_places():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    department = data.get('department')
    dates = data.get('dates', [])
    start_time = data.get('start_time')
    end_time = data.get('end_time')

    if not department or not dates or not start_time or not end_time:
        return jsonify({'error': 'Missing parameters'}), 400

    available_places = booking_system.get_available_places(department, dates, start_time, end_time)

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


@app.route('/schedule')
def schedule():
    # Получаем параметры из URL
    selected_date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    view_type = request.args.get('view', 'day')  # 'day' или 'week'
    department_filter = request.args.get('department', 'all')

    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = datetime.now().date()

    # Рассчитываем даты для навигации
    if view_type == 'week':
        # Для недельного представления переключаемся на неделю вперед/назад
        days_delta = 7
    else:
        # Для дневного представления переключаемся на день вперед/назад
        days_delta = 1

    previous_date = selected_date - timedelta(days=days_delta)
    next_date = selected_date + timedelta(days=days_delta)

    # Получаем все бронирования
    query = db.session.query(Booking, Workplace, User).join(Workplace).join(User)

    # Фильтрация по отделу
    if department_filter != 'all':
        query = query.filter(Workplace.department == department_filter)

    bookings_data = query.order_by(Booking.start_time).all()

    # Формируем расписание
    schedule_data = {}
    for booking, workplace, user in bookings_data:
        date_str = booking.start_time.date().isoformat()
        if date_str not in schedule_data:
            schedule_data[date_str] = {}

        place_key = f"{workplace.department} - {workplace.number}"
        schedule_data[date_str][place_key] = {
            'user': user.username,
            'start': booking.start_time.time().isoformat(),
            'end': booking.end_time.time().isoformat(),
            'department': workplace.department
        }

    # Для недельного представления
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

    # Получаем список отделов для фильтра
    departments = booking_system.get_departments()

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
                           departments=departments,
                           department_filter=department_filter)


@app.route('/save_default_department', methods=['POST'])
def save_default_department():
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    department = data.get('department')
    save_as_default = data.get('save_as_default', False)

    if not department and save_as_default:
        return jsonify({'error': 'Missing department parameter'}), 400

    if user_manager.set_default_department(session['username'], department, save_as_default):
        if save_as_default:
            return jsonify({'success': True, 'message': 'Отдел сохранен по умолчанию'})
        else:
            return jsonify({'success': True, 'message': 'Отдел по умолчанию удален'})

    return jsonify({'error': 'Failed to save default department'}), 400


@app.route('/logout')
def logout():
    user_manager.logout()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('login'))


if __name__ == '__main__':
    # Создаем таблицы в БД перед запуском приложения
    with app.app_context():
        db.create_all()

        # Создаем рабочие места, если их нет
        if Workplace.query.count() == 0:
            # Места для РЦИТ Ижевск (15 мест)
            for i in range(1, 16):
                workplace = Workplace(number=i, department='РЦИТ Ижевск')
                db.session.add(workplace)

            # Места для ООКИС Москва (10 мест)
            for i in range(1, 11):
                workplace = Workplace(number=i, department='ООКИС Москва')
                db.session.add(workplace)

            db.session.commit()
            print("Созданы рабочие места: 15 для РЦИТ Ижевск, 10 для ООКИС Москва")


    app.run(host='0.0.0.0', port=5000, debug=True)

