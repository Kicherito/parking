from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import re

app = Flask(__name__)
app.secret_key = 'super_secret_key_12345'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)


class UserManager:
    def __init__(self):
        self.users = {}
        self.current_user = None

    def register(self, username: str, password: str) -> bool:
        if username in self.users:
            return False
        self.users[username] = password
        return True

    def login(self, username: str, password: str) -> bool:
        if username in self.users and self.users[username] == password:
            self.current_user = username
            return True
        return False

    def logout(self):
        self.current_user = None

    def is_authenticated(self) -> bool:
        return self.current_user is not None


class OfficeBookingSystem:
    def __init__(self):
        self.workplaces = list(range(1, 16))
        self.bookings = []
        self.working_hours = (8, 18)  # Рабочие часы с 8:00 до 18:00

    def is_available(self, place: int, start: datetime, end: datetime) -> bool:
        """Проверка доступности места в указанный период"""
        # Проверяем, что время бронирования в рабочих часах
        if not (self.working_hours[0] <= start.hour < self.working_hours[1] and
                self.working_hours[0] < end.hour <= self.working_hours[1]):
            return False

        for booking in self.bookings:
            if booking['place'] != place:
                continue

            booking_start = datetime.fromisoformat(booking['start'])
            booking_end = datetime.fromisoformat(booking['end'])

            # Проверяем пересечение интервалов времени
            if (start < booking_end) and (end > booking_start):
                return False
        return True

    def book_place(self, place: int, user: str, dates: list, start_time: str, end_time: str) -> list:
        """Бронирование места для нескольких дат с одинаковым временем"""
        results = []

        # Проверяем номер места
        if place not in self.workplaces:
            return [("error", "Неверный номер места")]

        # Проверяем корректность времени
        try:
            # Создаем временные объекты для проверки
            time_dummy_date = "2000-01-01"  # Любая дата для проверки времени
            start_dt_test = datetime.fromisoformat(f"{time_dummy_date}T{start_time}")
            end_dt_test = datetime.fromisoformat(f"{time_dummy_date}T{end_time}")

            # Проверка что время окончания позже времени начала
            if end_dt_test <= start_dt_test:
                return [("error", "Время окончания должно быть позже времени начала")]

            # Проверка что время начала не раньше 08:00
            if start_dt_test.hour < self.working_hours[0]:
                return [("error", f"Бронирование возможно только с {self.working_hours[0]}:00")]

            # Проверка что время окончания не позже 18:00
            if end_dt_test.hour > self.working_hours[1] or (
                    end_dt_test.hour == self.working_hours[1] and end_dt_test.minute > 0
            ):
                return [("error", f"Бронирование возможно только до {self.working_hours[1]}:00")]
        except ValueError:
            return [("error", "Неверный формат времени")]

        # Обрабатываем каждую дату
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
            self.bookings.append({
                'place': place,
                'user': user,
                'start': start_dt.isoformat(),
                'end': end_dt.isoformat()
            })

            results.append(("success", f"Место {place} забронировано на {date_str} с {start_time} до {end_time}"))

        return results

    def cancel_booking(self, booking_id: int) -> str:
        """Отмена бронирования по ID"""
        if booking_id < 0 or booking_id >= len(self.bookings):
            return "Бронирование не найдено"

        if self.bookings[booking_id]['user'] != session.get('username'):
            return "Вы не можете отменить чужое бронирование"

        self.bookings.pop(booking_id)
        return "Бронирование успешно отменено"

    def show_user_bookings(self, user: str) -> list:
        """Получение бронирований пользователя с ID"""
        user_bookings = []
        for i, booking in enumerate(self.bookings):
            if booking['user'] == user:
                # Конвертируем строки в datetime для сортировки
                booking_start = datetime.fromisoformat(booking['start'])
                booking_end = datetime.fromisoformat(booking['end'])

                booking_with_id = {
                    'id': i,  # Добавляем ID для отмены
                    'place': booking['place'],
                    'start': booking['start'],
                    'end': booking['end'],
                    'start_dt': booking_start,
                    'end_dt': booking_end
                }
                user_bookings.append(booking_with_id)

        # Сортируем бронирования по дате начала
        user_bookings.sort(key=lambda b: b['start_dt'])
        return user_bookings

    def get_available_places(self, start: datetime, end: datetime) -> list:
        """Получение доступных мест на указанный период"""
        available_places = []
        for place in self.workplaces:
            if self.is_available(place, start, end):
                available_places.append(place)
        return available_places

    def get_booking_schedule(self, date: datetime) -> dict:
        """Получение расписания бронирований на определенную дату"""
        schedule = {place: [] for place in self.workplaces}
        target_date = date.date()

        for booking in self.bookings:
            booking_start = datetime.fromisoformat(booking['start'])
            booking_end = datetime.fromisoformat(booking['end'])

            # Если бронирование затрагивает целевую дату
            if booking_start.date() <= target_date <= booking_end.date():
                # Определяем временной интервал для целевой даты
                start_time = booking_start.time() if booking_start.date() == target_date else datetime.min.time()
                end_time = booking_end.time() if booking_end.date() == target_date else datetime.max.time()

                schedule[booking['place']].append({
                    'user': booking['user'],
                    'start': start_time.strftime('%H:%M'),
                    'end': end_time.strftime('%H:%M')
                })

        # Сортируем бронирования по времени начала
        for place in schedule:
            schedule[place].sort(key=lambda b: b['start'])

        return schedule


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
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if user_manager.login(username, password):
            session['username'] = username
            session.permanent = True  # Делаем сессию постоянной
            return redirect(url_for('dashboard'))
        error = "Неверный логин или пароль"

    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        # Простая валидация
        if len(username) < 3:
            error = "Логин должен содержать минимум 3 символа"
        elif len(password) < 4:
            error = "Пароль должен содержать минимум 4 символа"
        elif user_manager.register(username, password):
            flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
            return redirect(url_for('login'))
        else:
            error = "Пользователь с таким логином уже существует"

    return render_template('register.html', error=error)


@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    bookings = booking_system.show_user_bookings(username)
    today = datetime.now().date().isoformat()
    min_date = datetime.now().strftime("%Y-%m-%d")
    max_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    # Значения по умолчанию для времени
    start_time = "08:00"
    end_time = "18:00"

    # Если есть данные в сессии, используем их
    if 'form_data' in session:
        start_time = session['form_data'].get('start_time', "08:00")
        end_time = session['form_data'].get('end_time', "18:00")
        session.pop('form_data', None)

    # Получаем сообщения из flash
    messages = []
    if 'message' in request.args:
        messages.append(('success', request.args['message']))

    return render_template('dashboard.html',
                           username=username,
                           bookings=bookings,
                           today=today,
                           min_date=min_date,
                           max_date=max_date,
                           start_time=start_time,
                           end_time=end_time,
                           messages=messages,
                           working_hours=booking_system.working_hours)


@app.route('/check_availability', methods=['POST'])
def check_availability():
    if 'username' not in session:
        return redirect(url_for('login'))

    start_date = request.form.get('start_date', '')
    start_time = request.form.get('start_time', '08:00')
    end_date = request.form.get('end_date', '')
    end_time = request.form.get('end_time', '18:00')

    # Исправление 1: если end_date < start_date, то end_date = start_date
    if end_date and start_date and end_date < start_date:
        end_date = start_date

    error = None
    available_places = []
    selected_date = start_date  # Для отображения в интерфейсе

    try:
        # Создаем объекты datetime из строк
        start_dt = datetime.fromisoformat(f"{start_date}T{start_time}")
        end_dt = datetime.fromisoformat(f"{end_date}T{end_time}")

        # Проверяем корректность временного интервала
        if start_dt >= end_dt:
            error = "Время окончания должно быть позже времени начала"
        else:
            available_places = booking_system.get_available_places(start_dt, end_dt)
    except ValueError:
        error = "Неверный формат даты или времени"

    # Сохраняем данные формы в сессии для повторного использования
    session['form_data'] = {
        'start_time': start_time,
        'end_time': end_time
    }

    today = datetime.now().date().isoformat()
    min_date = datetime.now().strftime("%Y-%m-%d")
    max_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    return render_template('dashboard.html',
                           username=session['username'],
                           bookings=booking_system.show_user_bookings(session['username']),
                           available_places=available_places,
                           error=error,
                           today=today,
                           min_date=min_date,
                           max_date=max_date,
                           start_date=start_date,
                           start_time=start_time,
                           end_date=end_date,
                           end_time=end_time,
                           selected_date=selected_date,
                           working_hours=booking_system.working_hours)


@app.route('/book', methods=['POST'])
def book():
    if 'username' not in session:
        return redirect(url_for('login'))

    place = request.form.get('place', '')
    dates_str = request.form.get('dates', '')
    start_time = request.form.get('start_time', '08:00')
    end_time = request.form.get('end_time', '18:00')
    username = session['username']

    # Преобразуем строку с датами в список
    dates = dates_str.split(',') if dates_str else []

    if not dates:
        flash("Не выбрано ни одной даты для бронирования", 'danger')
        return redirect(url_for('dashboard'))

    try:
        place = int(place)
        # Выполняем бронирование
        results = booking_system.book_place(place, username, dates, start_time, end_time)

        success_messages = []
        error_messages = []
        for status, msg in results:
            if status == "success":
                success_messages.append(msg)
            else:
                error_messages.append(msg)

        if success_messages:
            flash("Успешные бронирования:<br>" + "<br>".join(success_messages), 'success')
        if error_messages:
            flash("Ошибки бронирования:<br>" + "<br>".join(error_messages), 'danger')

        # Сохраняем данные формы в сессии
        session['form_data'] = {
            'place': place,
            'start_time': start_time,
            'end_time': end_time
        }

    except ValueError:
        flash("Ошибка: введите корректный номер места", 'danger')
    except Exception as e:
        flash(f"Ошибка бронирования: {str(e)}", 'danger')

    return redirect(url_for('dashboard'))


@app.route('/cancel/<int:booking_id>')
def cancel(booking_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    result = booking_system.cancel_booking(booking_id)
    flash(result, 'success')
    return redirect(url_for('dashboard'))


@app.route('/schedule')
def schedule():
    if 'username' not in session:
        return redirect(url_for('login'))

    date_str = request.args.get('date', datetime.now().date().isoformat())
    min_date = datetime.now().strftime("%Y-%m-%d")
    max_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        date = datetime.fromisoformat(date_str).date()
        date_dt = datetime.combine(date, datetime.min.time())
    except ValueError:
        date_dt = datetime.now()

    schedule = booking_system.get_booking_schedule(date_dt)
    formatted_date = date_dt.strftime('%d.%m.%Y')

    return render_template('schedule.html',
                           username=session['username'],
                           schedule=schedule,
                           selected_date=date_dt.date().isoformat(),
                           formatted_date=formatted_date,
                           min_date=min_date,
                           max_date=max_date,
                           working_hours=booking_system.working_hours)


@app.route('/logout')
def logout():
    session.pop('username', None)
    user_manager.logout()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)