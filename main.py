import os
import sqlite3
import threading
from time import sleep
from uuid import uuid4
from hashlib import md5
from requests import Session
from requests.exceptions import ReadTimeout, ConnectionError, HTTPError
from json import loads, JSONDecodeError
from random import choice
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.scrollview import ScrollView
from kivy.uix.progressbar import ProgressBar
from kivy.uix.gridlayout import GridLayout
from kivy.properties import StringProperty, NumericProperty, ColorProperty
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.clock import Clock
from kivy.animation import Animation
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

user_agents = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36',
    'Mozilla/5.0 (Linux; Android 10; Pixel 3 XL) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 11; Galaxy S21) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Mobile Safari/537.36',
]

url_base = 'https://iran.fruitcraft.ir/'
Window.clearcolor = (0.05, 0.05, 0.15, 1)  

def decode(data):
    return '&'.join(f"{key}={value}" for key, value in data.items())

def create_session(proxies=None):
    session = Session()
    session.headers.update({
        'User-Agent': choice(user_agents),
        'Accept-Encoding': 'gzip, deflate, br',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def safe_load_json(response):
    try:
        return loads(response.text)
    except JSONDecodeError:
        return None

def load(session, restore_key, app_instance):
    data = {
        'game_version': '1.7.10655',
        'device_name': 'unknown',
        'os_version': '10',
        'model': 'SM-A750F',
        'udid': str(uuid4().int),
        'store_type': 'iraqapps',
        'restore_key': restore_key,
        'os_type': 2
    }
    attempts = 5
    for attempt in range(attempts):
        app_instance.update_result(f'[color=ffaa00]Attempt {attempt + 1}/{attempts}: Connecting to server...[/color]') 
        app_instance.update_progress((attempt + 1) * (100 // attempts))
        try:
            response = session.post(f'{url_base}player/load', data=decode(data), timeout=5)
            response.raise_for_status()
            result = safe_load_json(response)
            if result is None:
                app_instance.update_result('[color=ff5555]Error decoding JSON response[/color]') 
                return {'status': False}
            app_instance.update_result('[color=55ff55]Successfully connected![/color]')  
            return result
        except (ReadTimeout, ConnectionError) as e:
            wait_time = 5 * (attempt + 1)
            app_instance.update_result(f'[color=ffaa00]Connection issue: {e}. Waiting {wait_time}s...[/color]')  
            sleep(wait_time)
        except HTTPError as http_err:
            app_instance.update_result(f'[color=ff5555]HTTP error: {http_err}[/color]')  
            break
    app_instance.update_result('[color=ff5555]All connection attempts failed[/color]')  
    return {'status': False}

def fetch_players_from_server(session, min_level, app_instance):
    attempts = 5
    for attempt in range(attempts):
        app_instance.update_result(f'[color=ffaa00]Attempt {attempt + 1}/{attempts}: Fetching players...[/color]') 
        app_instance.update_progress((attempt + 1) * (100 // attempts))
        try:
            response = session.get(f'{url_base}battle/getopponents', timeout=5)
            response.raise_for_status()
            players_data = safe_load_json(response)
            if players_data and 'data' in players_data:
                players = players_data['data'].get('players', [])
                filtered_players = [{
                    'id': p['id'],
                    'def_power': p['def_power'],
                    'level': p['level'],
                    'league_id': p['league_id'],
                    'gold': p['gold'],
                    'name': p['name'],
                    'tribe': p['tribe_name']
                } for p in players if p['level'] >= min_level]
                app_instance.update_result(f'[color=55ff55]Fetched {len(filtered_players)} players[/color]') 
                return filtered_players
        except (ReadTimeout, ConnectionError) as e:
            wait_time = 5 * (attempt + 1)
            app_instance.update_result(f'[color=ffaa00]Error fetching players: {e}. Retrying in {wait_time}s...[/color]') 
            sleep(wait_time)
        except HTTPError as http_err:
            app_instance.update_result(f'[color=ff5555]HTTP error: {http_err}[/color]')  
            break
    app_instance.update_result('[color=ff5555]Failed to fetch players[/color]') 
    return []

def create_or_open_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS Accounts (
                        id TEXT UNIQUE,
                        power NUMERIC,
                        level NUMERIC,
                        league NUMERIC,
                        PRIMARY KEY(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS StrongPlayers (
                        id TEXT UNIQUE,
                        PRIMARY KEY(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS WeakPlayers (
                        id TEXT UNIQUE,
                        PRIMARY KEY(id))''')
    conn.commit()
    return conn, cursor


def update_players_in_db(cursor, players, min_level_for_storage):
    for player in players:
        if player['level'] >= min_level_for_storage:
            cursor.execute('''INSERT INTO Accounts (id, power, level, league)
                              VALUES (?, ?, ?, ?)
                              ON CONFLICT(id) DO UPDATE SET
                                  power=excluded.power,
                                  level=excluded.level,
                                  league=excluded.league''',
                           (player['id'], player['def_power'], player['level'], player['league_id']))


def get_enemies_from_db(db_path, min_level):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT id, power, level, league FROM Accounts WHERE level >= ?', (min_level,))
    enemies = cursor.fetchall()
    conn.close()
    return [{'id': e[0], 'power': e[1], 'level': e[2], 'league': e[3]} for e in enemies]


def battle(session, opponent_id, q, cards, app_instance):
    data = {'opponent_id': opponent_id, 'check': md5(str(q).encode()).hexdigest(),
            'cards': str(cards).replace(' ', ''), 'attacks_in_today': 0}
    attempts = 5
    for attempt in range(attempts):
        app_instance.update_result(f'[color=ffaa00]Attempt {attempt + 1}/{attempts}: Battling ID {opponent_id}...[/color]') 
        app_instance.update_progress((attempt + 1) * (100 // attempts))
        try:
            response = session.get(f'{url_base}battle/battle?' + decode(data), timeout=5)
            response.raise_for_status()
            if response.status_code == 429:
                app_instance.update_result('[color=ffaa00]Rate limit exceeded (429). Pausing for 60s...[/color]') 
                sleep(60)
                return {}
            app_instance.update_result('[color=55ff55]Battle completed![/color]') 
            return safe_load_json(response)
        except (ReadTimeout, ConnectionError) as e:
            wait_time = 30
            app_instance.update_result(f'[color=ffaa00]Connection issue in battle: {e}. Waiting {wait_time}s...[/color]')  
            sleep(wait_time)
        except HTTPError as http_err:
            app_instance.update_result(f'[color=ff5555]HTTP error: {http_err}[/color]') 
            break
    app_instance.update_result('[color=ff5555]All battle attempts failed[/color]')  
    return {}

def attack_offline(session, cursor, db_file, max_power, min_level, cards, attacks_per_player, load_data, rest_after_attacks, rest_duration, speed, request_speed, save_to_db, app_instance):
    if 'data' not in load_data or 'q' not in load_data['data']:
        app_instance.update_result('[color=ff5555]Error: \'q\' key not found. Using default_q[/color]') 
        q = 'default_q'
    else:
        q = load_data['data']['q']

    win = 0
    lost = 0
    xp = 0
    doon = 0
    attacked = {}
    attack_count = 0

    while app_instance.is_running:
        enemies = get_enemies_from_db(db_file, min_level)
        if not enemies:
            app_instance.update_result('[color=ffaa00]No enemies found in database[/color]') 
            enemies = fetch_players_from_server(session, min_level, app_instance)
            if save_to_db:
                update_players_in_db(cursor, enemies, min_level)
                cursor.connection.commit()
            if not enemies:
                app_instance.update_result('[color=ff5555]No players fetched from server[/color]') 
                return

        enemies.sort(key=lambda x: (x['power'], -x['level']))
        app_instance.update_result('[color=55ff55]Enemies available for attack:[/color]')  
        app_instance.update_result('[color=cccccc]================[/color]') 
        for enemy in enemies:
            app_instance.update_result(
                f'[color=00ccff]ID: {enemy["id"]}[/color] | '
                f'[color=ffaa00]Power: {enemy["power"]}[/color] | '
                f'[color=55ff55]Level: {enemy["level"]}[/color]'
            ) 
        app_instance.update_result('[color=cccccc]================[/color]') 

        app_instance.update_result('[color=cccccc]Analyzing players... Waiting 10s[/color]') 
        sleep(10)

        for enemy in enemies:
            if not app_instance.is_running:
                break
            attacked[enemy['id']] = 0
            app_instance.update_result(
                f'[color=55ff55]Attacking player ID: {enemy["id"]}...[/color] '
                f'[color=55ff55]Level: {enemy["level"]}[/color]'
            ) 

            for i in range(attacks_per_player):
                if not app_instance.is_running:
                    break
                try:
                    q_response = battle(session, enemy['id'], q, [cards[0]], app_instance)
                    if q_response.get('data', {}).get('xp_added', 0) > 0:
                        xp += q_response["data"]["xp_added"]
                        win += 1
                    else:
                        lost += 1
                        break

                    doon = q_response.get('data', {}).get('weekly_score', 0)
                    if 'data' in q_response and 'q' in q_response['data']:
                        q = q_response['data']['q']
                    attacked[enemy['id']] += 1
                    app_instance.update_result(
                        f'[color=55ff55]ID: {enemy["id"]}[/color] | '
                        f'[color=00ccff]Win: {win}[/color] | '
                        f'[color=ff5555]Lose: {lost}[/color] | '
                        f'[color=ffaa00]Doon: {doon}[/color] | '
                        f'[color=55ff55]XP: {xp}[/color]'
                    ) 

                    attack_count += 1
                    sleep(speed)
                except (KeyError, JSONDecodeError):
                    app_instance.update_result('[color=ff5555]Error encountered. Retrying...[/color]')
                    sleep(2)
                except Exception as e:
                    app_instance.update_result(f'[color=ff5555]Unexpected error: {e}[/color]')
                    return

                if cards:
                    cards.append(cards[0])
                    cards.pop(0)

            app_instance.update_result(f'[color=cccccc]Finished attacking ID: {enemy["id"]}... Waiting {request_speed}s[/color]') 
            sleep(request_speed)

            if attack_count >= rest_after_attacks:
                app_instance.update_result(f'[color=ffaa00]Resting for {rest_duration}s after {attack_count} attacks[/color]')
                sleep(rest_duration)
                attack_count = 0

class SplashScreen(BoxLayout):
    opacity_value = NumericProperty(0)

    def __init__(self, switch_page_callback, **kwargs):
        super().__init__(**kwargs)
        self.switch_page = switch_page_callback
        self.orientation = 'vertical'

        with self.canvas.before:
            Color(0.05, 0.05, 0.15, 1) 
            self.rect = Rectangle(pos=self.pos, size=self.size)
            self.bind(pos=self.update_rect, size=self.update_rect)

        self.label = Label(
            text='[b]DARCOB[/b]',
            font_size=dp(30),
            markup=True,
            color=(0, 0.8, 1, 1), 
            opacity=0
        )
        self.add_widget(self.label)

        
        self.start_animation()

    def update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size

    def start_animation(self):
        anim = Animation(opacity=1, duration=2, t='out_elastic') + Animation(font_size=dp(60), duration=2, t='out_elastic')
        anim.bind(on_complete=lambda *args: Clock.schedule_once(self.go_to_main, 1))
        anim.start(self.label)

    def go_to_main(self, dt):
        self.switch_page('page1')

class Page1(BoxLayout):
    def __init__(self, switch_page_callback, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = dp(20)
        self.spacing = dp(15)
        self.switch_page = switch_page_callback

        with self.canvas.before:
            Color(0.05, 0.05, 0.15, 1) 
            self.rect = Rectangle(pos=self.pos, size=self.size)
            self.bind(pos=self.update_rect, size=self.update_rect)

        
        title = Label(
            text="[b]Welcome to DARCOB Script[/b]",
            font_size=dp(35),
            markup=True,
            color=(0, 0.8, 1, 1) 
        )
        self.add_widget(title)

    
        account_layout = BoxLayout(size_hint=(1, None), height=dp(60))
        account_label = Label(
            text="Number of Accounts:",
            font_size=dp(20),
            color=(0.9, 0.9, 1, 1) 
        )
        self.account_spinner = Spinner(
            text="1",
            values=["1", "2", "3"],
            size_hint=(0.3, 1),
            background_color=(0, 0.6, 0.8, 1), 
            background_normal='',
            color=(1, 1, 1, 1)
        )
        account_layout.add_widget(account_label)
        account_layout.add_widget(self.account_spinner)
        self.add_widget(account_layout)

    
        self.next_button = Button(
            text="Next ->",
            font_size=dp(20),
            size_hint=(1, None),
            height=dp(60),
            background_normal='',
            background_color=(0, 0.6, 0.8, 1)
        )
        self.next_button.bind(on_press=self.go_to_page2)
        self.add_widget(self.next_button)

    def update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size

    def go_to_page2(self, instance):
        self.switch_page('page2', num_accounts=int(self.account_spinner.text))

class Page2(BoxLayout):
    def __init__(self, switch_page_callback, num_accounts, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = dp(20)
        self.spacing = dp(10)
        self.switch_page = switch_page_callback
        self.num_accounts = num_accounts
        self.current_account = 0
        self.account_inputs = []

        with self.canvas.before:
            Color(0.05, 0.05, 0.15, 1) 
            self.rect = Rectangle(pos=self.pos, size=self.size)
            self.bind(pos=self.update_rect, size=self.update_rect)

    
        self.input_panel = GridLayout(cols=1, size_hint_y=None, padding=dp(10), spacing=dp(5))
        self.input_panel.bind(minimum_height=self.input_panel.setter('height'))

    
        scroll_view = ScrollView(size_hint=(1, 0.75), do_scroll_x=False, do_scroll_y=True)
        scroll_view.add_widget(self.input_panel)
        self.add_widget(scroll_view)

    
        self.next_button = Button(
            text="Next ->",
            font_size=dp(20),
            size_hint=(1, None),
            height=dp(60),
            background_normal='',
            background_color=(0, 0.6, 0.8, 1),
            disabled=True
        )
        self.next_button.bind(on_press=self.next_account)
        self.add_widget(self.next_button)


        self.start_button = Button(
            text="Start",
            font_size=dp(20),
            size_hint=(1, None),
            height=dp(60),
            background_normal='',
            background_color=(0, 1, 0.4, 1),
            disabled=True
        )
        self.start_button.bind(on_press=self.start_attack)
        self.add_widget(self.start_button)

        self.show_account_inputs()

    def update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size

    def validate_input(self, text, field_type):
        if not text and field_type not in ['power', 'save_to_db']:
            return True
        if field_type in ['power', 'min_level', 'min_level_storage', 'attacks_per_player', 'rest_after_attacks', 'rest_duration']:
            try:
                int(text)
                return True
            except ValueError:
                return False
        elif field_type in ['attack_speed', 'request_speed']:
            try:
                float(text)
                return True
            except ValueError:
                return False
        elif field_type == 'save_to_db':
            return text.lower() in ['yes', 'no']
        return True

    def validate_field(self, instance, value, field_type):
        if not self.validate_input(value, field_type):
            instance.background_color = (1, 0, 0, 0.5)
            instance.hint_text = "Please enter a number" if field_type != 'save_to_db' else "Please enter Yes or No"
        else:
            instance.background_color = (0.2, 0.4, 0.6, 1)
            instance.hint_text = f"Power {self.current_account + 1}" if field_type == 'power' else instance.hint_text

    def show_account_inputs(self):
        self.input_panel.clear_widgets()
        print(f"Adding inputs for Account {self.current_account + 1}") 


        self.input_panel.add_widget(Label(
            text=f"[b]Account {self.current_account + 1}[/b]",
            font_size=dp(24),
            color=(1, 1, 1, 1), 
            markup=True,
            size_hint_y=None,
            height=dp(40)
        ))

        inputs = {
            'restore_key': TextInput(hint_text=f"Restore Key {self.current_account + 1}", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)]),
            'power': TextInput(hint_text=f"Power {self.current_account + 1}", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)]),
            'min_level': TextInput(hint_text="Level Up to Attack", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)]),
            'min_level_storage': TextInput(hint_text="Level Up to Save Database", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)]),
            'attacks_per_player': TextInput(hint_text="Number of Attacks to Enemy", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)]),
            'rest_after_attacks': TextInput(hint_text="Rest After How Many Attacks", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)]),
            'rest_duration': TextInput(hint_text="Rest Duration (seconds)", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)]),
            'attack_speed': TextInput(hint_text="Attack Speed (seconds)", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)]),
            'request_speed': TextInput(hint_text="Request Speed (seconds)", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)]),
            'save_to_db': TextInput(hint_text="Save to DB (Yes/No)", multiline=False, background_color=(0.2, 0.4, 0.6, 1), foreground_color=(1, 1, 1, 1), size_hint_y=None, height=dp(50), font_size=dp(16), padding=[dp(10), dp(10), dp(10), dp(10)])
        }

        for field, input_widget in inputs.items():
            print(f"Adding {field} input") 
            self.input_panel.add_widget(input_widget)
            if field != 'restore_key':
                input_widget.bind(text=lambda instance, value, f=field: self.validate_field(instance, value, f))

        self.account_inputs.append(inputs)
        self.next_button.disabled = self.current_account == self.num_accounts - 1
        self.start_button.disabled = self.current_account < self.num_accounts - 1

    def next_account(self, instance):
        if self.current_account < self.num_accounts - 1:
            self.current_account += 1
            self.show_account_inputs()
            if self.current_account == self.num_accounts - 1:
                self.next_button.text = "Finish"
        else:
            self.next_button.disabled = True
            self.start_button.disabled = False
            self.next_button.opacity = 0

    def start_attack(self, instance):
        self.switch_page('page3', account_inputs=self.account_inputs)

class Page3(BoxLayout):
    result_text = StringProperty("")
    progress_value = NumericProperty(0)

    def __init__(self, switch_page_callback, account_inputs, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = dp(20)
        self.spacing = dp(10)
        self.switch_page = switch_page_callback
        self.account_inputs = account_inputs
        self.threads = []
        self.conns = []
        self.is_running = True

        with self.canvas.before:
            Color(0.05, 0.05, 0.15, 1)
            self.rect = Rectangle(pos=self.pos, size=self.size)
            self.bind(pos=self.update_rect, size=self.update_rect)

        self.progress_bar = ProgressBar(max=100, value=0, size_hint=(1, None), height=dp(20))
        self.bind(progress_value=self.progress_bar.setter('value'))
        self.add_widget(self.progress_bar)

        self.result_label = Label(
            text='',
            font_size=dp(16),
            color=(1, 1, 1, 1),
            size_hint_y=None,
            markup=True
        )
        self.result_label.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
        self.result_label.bind(texture_size=lambda instance, value: setattr(instance, 'height', value[1]))
        self.bind(result_text=self.result_label.setter('text'))

        scroll_view = ScrollView(size_hint=(1, 0.75), do_scroll_x=False, do_scroll_y=True)
        scroll_view.add_widget(self.result_label)
        self.add_widget(scroll_view)

        self.stop_button = Button(
            text="Stop",
            font_size=dp(20),
            size_hint=(1, None),
            height=dp(60),
            background_normal='',
            background_color=(1, 0.4, 0.4, 1)
        )
        self.stop_button.bind(on_press=self.stop_attack)
        self.add_widget(self.stop_button)

        self.start_threads()

    def update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size

    def update_result(self, text):
        Clock.schedule_once(lambda dt: setattr(self, 'result_text', self.result_text + "\n" + text))

    def update_progress(self, value):
        self.progress_value = value

    def start_threads(self):
        self.update_result('[color=55ff55]Welcome to the Game Automation Script![/color]')
        self.update_result('[color=cccccc]================[/color]')
        num_accounts = len(self.account_inputs)
        sessions = []
        load_data = []
        invalid_accounts = []

        for i in range(num_accounts):
            account = self.account_inputs[i]
            restore_key = account['restore_key'].text
            if not restore_key:
                invalid_accounts.append(i + 1)
                self.update_result(f'[color=ff5555]Error: Account {i + 1} is invalid (no restore key)![/color]')
                continue

            session = create_session()
            load_result = load(session, restore_key, self)
            if not load_result.get('status', False):
                invalid_accounts.append(i + 1)
                self.update_result(f'[color=ff5555]Connection failed for Account {i + 1}![/color]')
                continue

            account_info = load_result['data']
            tribe_name = account_info['tribe']['name']
            self.update_result(f'[color=55ff55]Connection successful for Account {i + 1}![/color]')
            self.update_result(
                f'[color=cccccc]Account Name: {account_info["name"]}[/color] | '
                f'[color=55ff55]Level: {account_info["level"]}[/color] | '
                f'[color=ffaa00]Gold: {account_info["gold"]}[/color] | '
                f'[color=00ccff]Tribe: {tribe_name}[/color]'
            )  # ترکیب رنگ‌ها
            self.update_result('[color=cccccc]================[/color]')

            sessions.append(session)
            load_data.append({
                'data': load_result,
                'power': int(account['power'].text) if account['power'].text else 0,
                'min_level': int(account['min_level'].text) if account['min_level'].text else 8,
                'min_level_storage': int(account['min_level_storage'].text) if account['min_level_storage'].text else 8,
                'attacks_per_player': int(account['attacks_per_player'].text) if account['attacks_per_player'].text else 1,
                'rest_after_attacks': int(account['rest_after_attacks'].text) if account['rest_after_attacks'].text else 10,
                'rest_duration': int(account['rest_duration'].text) if account['rest_duration'].text else 60,
                'attack_speed': float(account['attack_speed'].text) if account['attack_speed'].text else 1.0,
                'request_speed': float(account['request_speed'].text) if account['request_speed'].text else 1.0,
                'save_to_db': account['save_to_db'].text.lower() == 'yes'
            })

        if invalid_accounts:
            self.update_result(f'[color=ff5555]Error: Accounts {", ".join(map(str, invalid_accounts))} are invalid![/color]')
            self.is_running = False
            return

        account_info = [data['data']['data'] for data in load_data]
        cards = [[i['id'] for i in info['cards'] if i['power'] < 100] for info in account_info]

        if any(len(card) < 20 for card in cards):
            self.update_result('[color=ff5555]One or more accounts have less than 20 cards![/color]')
            self.is_running = False
            return

        players = [fetch_players_from_server(sessions[i], load_data[i]['min_level'], self) for i in range(len(load_data))]
        if not all(players[i] for i in range(len(load_data))):
            self.update_result('[color=ff5555]No players fetched from server for one or more accounts![/color]')
            self.is_running = False
            return

        league_ids = [players[i][0]['league_id'] for i in range(len(load_data))]
        db_files = [f'Leage_{league_ids[i]}_Account{i+1}.db' for i in range(len(load_data))]

        for i in range(len(load_data)):
            conn, cursor = create_or_open_db(db_files[i])
            self.conns.append(conn)
            self.update_result(f'[color=cccccc]Using database file \'{db_files[i]}\' for Account {i+1}[/color]')
            if load_data[i]['save_to_db']:
                update_players_in_db(cursor, players[i], load_data[i]['min_level_storage'])
                conn.commit()
                self.update_result(f'[color=55ff55]{len(players[i])} players fetched and stored in database for Account {i+1}[/color]')

            thread = threading.Thread(target=attack_offline, args=(
                sessions[i], cursor, db_files[i],
                load_data[i]['power'], load_data[i]['min_level'], cards[i],
                load_data[i]['attacks_per_player'], load_data[i],
                load_data[i]['rest_after_attacks'], load_data[i]['rest_duration'],
                load_data[i]['attack_speed'], load_data[i]['request_speed'],
                load_data[i]['save_to_db'], self
            ))
            self.threads.append(thread)
            thread.start()

    def stop_attack(self, instance):
        self.is_running = False
        self.update_result('[color=ff5555]Script stopped[/color]')
        for thread in self.threads:
            thread.join()
        for conn in self.conns:
            conn.close()
        self.switch_page('page1')

class DarCobApp(BoxLayout):
    current_page = StringProperty('splash')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.switch_page('splash')

    def switch_page(self, page, **kwargs):
        self.clear_widgets()
        self.current_page = page
        if page == 'splash':
            self.add_widget(SplashScreen(self.switch_page))
        elif page == 'page1':
            self.add_widget(Page1(self.switch_page))
        elif page == 'page2':
            self.add_widget(Page2(self.switch_page, kwargs['num_accounts']))
        elif page == 'page3':
            self.add_widget(Page3(self.switch_page, kwargs['account_inputs']))

class DarCob(App):
    def build(self):
        return DarCobApp()

if __name__ == "__main__":
    DarCob().run()