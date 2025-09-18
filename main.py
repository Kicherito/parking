from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
import re

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
    bookings = db.relationship('Booking', backref='user', lazy=True)


class Workplace(db.Model):
    __tablename__ = 'workplaces'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    bookings = db.relationship('Booking', backref='workplace', lazy=True)


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
            return True
        return False

    def logout(self):
        self.current_user = None
        session.pop('username', None)

    def is_authenticated(self) -> bool:
        return self.current_user is not None


class OfficeBookingSystem:
    def __init__(self):
        self.working_hours = (8, 18)

    def is_available(self, place: int, start: datetime, end: datetime) -> bool:
        if not (self.working_hours[0] <= start.hour < self.working_hours[1] and
                self.working_hours[0] < end.hour <= self.working_hours[1]):
            return False

        overlapping_bookings = Booking.query.join(Workplace).filter(
            Workplace.number == place,
            Booking.start_time < end,
            Booking.end_time > start
        ).count()

        return overlapping_bookings == 0

    def book_place(self, place: int, user: str, dates: list, start_time: str, end_time: str) -> list:
        results = []
        workplace = Workplace.query.filter_by(number=place).first()
        if not workplace:
            return [("error", "Неверный номер места")]

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
            if not self.is_available(place, start_dt, end_dt):
                results.append(("error", f"Место {place} занято на {date_str}"))
                continue

            # Добавляем бронирование
            new_booking = Booking(
                place_id=workplace.id,
                user_id=user_obj.id,
                start_time=start_dt,
                end_time=end_dt
            )
            db.session.add(new_booking)
            results.append(("success", f"Место {place} забронировано на {date_str}"))

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

    def show_user_bookings(self, user: str) -> list:
        user_obj = User.query.filter_by(username=user).first()
        if not user_obj:
            return []

        bookings = Booking.query.filter_by(user_id=user_obj.id).join(Workplace).order_by(Booking.start_time).all()

        user_bookings = []
        for booking in bookings:
            user_bookings.append({
                'id': booking.id,
                'place': booking.workplace.number,
                'start': booking.start_time.isoformat(),
                'end': booking.end_time.isoformat(),
                'start_dt': booking.start_time,
                'end_dt': booking.end_time
            })
        return user_bookings


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

    user_bookings = booking_system.show_user_bookings(session['username'])

    # Добавляем передачу working_hours и других переменных в шаблон
    return render_template(
        'dashboard.html',
        username=session['username'],
        bookings=user_bookings,
        working_hours=booking_system.working_hours,
        today=datetime.now().strftime('%d.%m.%Y'),
        min_date=datetime.now().strftime('%Y-%m-%d'),
        max_date=(datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
        now=datetime.now()  # Передаем текущее время
    )

@app.route('/check_availability', methods=['POST'])
def check_availability():
    if 'username' not in session:
        return redirect(url_for('login'))

    date = request.form['date']
    start_time = request.form['start_time']
    end_time = request.form['end_time']

    try:
        start_dt = datetime.fromisoformat(f"{date}T{start_time}")
        end_dt = datetime.fromisoformat(f"{date}T{end_time}")
    except ValueError:
        flash('Неверный формат даты или времени', 'error')
        return redirect(url_for('dashboard'))

    available_places = []
    for place in range(1, 16):
        if booking_system.is_available(place, start_dt, end_dt):
            available_places.append(place)

    # Вместо отдельного шаблона, используем dashboard.html и передаем данные
    user_bookings = booking_system.show_user_bookings(session['username'])
    return render_template(
        'dashboard.html',
        username=session['username'],
        bookings=user_bookings,
        working_hours=booking_system.working_hours,
        today=datetime.now().strftime('%d.%m.%Y'),
        min_date=datetime.now().strftime('%Y-%m-%d'),
        max_date=(datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
        available_places=available_places,  # Передаем доступные места
        date=date,
        start_time=start_time,
        end_time=end_time
    )


@app.route('/book', methods=['POST'])
def book():
    if 'username' not in session:
        return redirect(url_for('login'))

    place = int(request.form['place'])
    dates_str = request.form.get('dates', '')
    dates = dates_str.split(',') if dates_str else []
    start_time = request.form['start_time']
    end_time = request.form['end_time']

    print(f"Booking data: place={place}, dates={dates}, start_time={start_time}, end_time={end_time}")

    results = booking_system.book_place(place, session['username'], dates, start_time, end_time)

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

    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = datetime.now().date()

    # Рассчитываем даты для навигации
    previous_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)

    # Получаем все бронирования
    bookings = Booking.query.join(Workplace).join(User).order_by(Booking.start_time).all()

    # Формируем расписание
    schedule_data = {}
    for booking in bookings:
        date_str = booking.start_time.date().isoformat()
        if date_str not in schedule_data:
            schedule_data[date_str] = {}

        schedule_data[date_str][booking.workplace.number] = {
            'user': booking.user.username,
            'start': booking.start_time.time().isoformat(),
            'end': booking.end_time.time().isoformat()
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
                           max_date=(datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'))


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
            for i in range(1, 16):
                workplace = Workplace(number=i)
                db.session.add(workplace)
            db.session.commit()
            print("Созданы рабочие места 1-15")


    app.run(host='0.0.0.0', port=5000, debug=True)
