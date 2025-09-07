from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
import re

app = Flask(__name__)
app.secret_key = 'super_secret_key_12345'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Конфигурация PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://booking_user:your_password@localhost/office_booking_db'
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


# Инициализация БД
@app.before_request
def create_tables():
    db.create_all()
    # Создаем рабочие места, если их нет
    if Workplace.query.count() == 0:
        for i in range(1, 16):
            workplace = Workplace(number=i)
            db.session.add(workplace)
        db.session.commit()


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
            return True
        return False

    def logout(self):
        self.current_user = None

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

        # ... (логика проверки времени, как в вашем оригинальном коде)

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

    # ... (остальные методы, адаптированные для работы с БД)


# Инициализация систем
user_manager = UserManager()
booking_system = OfficeBookingSystem()

# Маршруты Flask (оставьте без изменений, как в вашем оригинальном коде)
# ... (index, login, register, dashboard, check_availability, book, cancel, schedule, logout)

if __name__ == '__main__':
    app.run(debug=True)