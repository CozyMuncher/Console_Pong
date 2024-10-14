import curses, concurrent.futures, logging
from random import choice, random
from math import ceil, sqrt
from os import get_terminal_size, path, makedirs
from time import time, sleep
from keyboard import is_pressed
from json import dump, load

config_file_path = "config.json"

if not path.exists("tmp"):
    makedirs("tmp")

if not path.isfile(config_file_path):
    config = {
        "paddle_length_modifier": 0.2,
        "paddle_speed": 0.4,
        "ball_speed": 1.5,
        "enemy_difficulty": 2.2,
        "score_condition": 3,
        "framerate": 120
    }

    with open(config_file_path, "w") as file:
        dump(config, file)

logging.basicConfig(
    filename="tmp/log.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
logger.info("Game Boot")


class Vector2:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def multiply_vec(self, vector):
        return Vector2(self.x * vector.x, self.y * vector.y)

    def multiply_int(self, integer):
        return Vector2(self.x * integer, self.y * integer)

    def add_vector(self, vector):
        return Vector2(self.x + vector.x, self.y + vector.y)

    def normalize(self):
        magnitude = sqrt(self.x**2 + self.y**2)

        # Normalize the vector
        self.x, self.y = self.x / magnitude, self.y / magnitude


class Stdinfo:
    def __init__(self, message: str, location: Vector2):
        self.message = message
        self.location = location

        self.message_length = len(message)
        self.location.x -= ceil(self.message_length / 2)
        self.location.y = (
            self.location.y if self.location.y % 2 == 0 else self.location.y - 1
        )

    def write(self, stdscr):
        stdscr.addstr(self.location.y, self.location.x, self.message)


class Paddle:
    def __init__(
        self,
        length: float,
        position: Vector2,
        direction: int,
        speed: float,
        bounds: Vector2,
        thickness=1,
    ):
        self.length = length
        self.position = position
        self.direction = direction
        self.speed = speed
        self.bounds = bounds
        self.thickness = thickness

    def move(self, movement: int):
        if self.position.y + movement * self.speed - ceil(self.length / 2) + 1 < 1:
            self.position.y = ceil(self.length / 2)
        elif (
            self.position.y + movement * self.speed + ceil(self.length / 2) - 1
            >= self.bounds.y
        ):
            self.position.y = self.bounds.y - ceil(self.length / 2) + 1
        else:
            self.position.y += movement * self.speed


class Ball:
    def __init__(
        self,
        position: Vector2,
        direction: Vector2,
        bounds: Vector2,
        speed: float,
        paddles: list[Paddle],
        buffer=0.2,
    ):
        self.position = position
        self.direction = direction
        self.bounds = bounds
        self.speed = speed
        self.paddles = paddles

        self._position = position
        self.initial_position = position
        self.buffer = buffer

        self.last_ricochet = 0

    def reset(self):
        self.position = self.initial_position

    def target_paddle(self):
        selected_paddle = choice(self.paddles)
        target_y = selected_paddle.position.y + choice([-1, 1]) * random() * (
            selected_paddle.length / 4
        )

        self.direction = Vector2(
            -1 * selected_paddle.position.x - self.position.x,
            target_y,
        )
        self.direction.normalize()

    def move(self):
        self._position = self.position

        self.position = self.position.add_vector(
            self.direction.multiply_int(self.speed)
        )

        # Check for OFB
        # Coll with top of game bounds
        if self.last_ricochet == 0:
            if self.position.y < 1:
                self.position.y += 1 - self.position.y
                self.direction.y *= -1
                self.last_ricochet = 5

            # Coll with bottom of game bounds
            elif self.position.y > self.bounds.y:
                self.position.y -= 2 * (self.position.y - self.bounds.y)
                self.direction.y *= -1
                self.last_ricochet = 5

            global player_score, opponent_score, scored, info
            # Check for OBS at scoring areas
            if self.position.x <= 0:
                # Enemy scores
                scored = True
                opponent_score += 1
                info.append(
                    Stdinfo(
                        "Opponent Scores!",
                        Vector2(ceil(self.bounds.x / 2), ceil(self.bounds.y / 5)),
                    )
                )

            elif self.position.x >= self.bounds.x:
                # Player scores
                scored = True
                player_score += 1
                info.append(
                    Stdinfo(
                        "Player Scores!",
                        Vector2(ceil(self.bounds.x / 2), ceil(self.bounds.y / 5)),
                    )
                )

        else:
            self.last_ricochet -= 1

        # Check for coll with paddles

        # Generate raycast
        # Creates a line
        # with eqn y = mx - mx1 + y1
        grad = self.direction.y / self.direction.x
        c = -grad * self.position.x + self.position.y

        for paddle in self.paddles:
            # Check if line passes through the line of the paddle
            # Assume the centre of paddle is paddle.y + paddle.direction * 0.5
            paddle_x = paddle.position.x + paddle.direction * paddle.thickness * 0.5

            if (
                self.position.x * paddle.direction <= paddle_x * paddle.direction
                and self._position.x * paddle.direction >= paddle_x * paddle.direction
            ):
                # Passes through the paddle line
                # Calculate x,y of coll with the line
                y_coll = grad * paddle_x + c

                # Check if y _coll between the paddles
                paddle_y_min = round(paddle.position.y) - (paddle.length - 1) / 2
                paddle_y_max = ceil(paddle.position.y) + (paddle.length - 1) / 2

                if y_coll >= paddle_y_min and y_coll <= paddle_y_max:
                    # Hits the paddle
                    # Change direction
                    self.direction.x *= -1

                    # Check for corner coll
                    if (
                        y_coll > paddle_y_min - self.buffer
                        and y_coll < paddle_y_min + self.buffer
                    ) or (
                        (
                            y_coll > paddle_y_max - self.buffer
                            and y_coll < paddle_y_max + self.buffer
                        )
                    ):
                        self.direction.y *= -1


class EnemyAI:
    def __init__(self, difficulty: float, paddle: Paddle, ball: Ball):
        self.difficulty = difficulty
        # Set to value between 1 - 3.
        # 4 has aimbot
        # 0 always avoid the ball

        self.paddle = paddle
        self.ball = ball

    def move_paddle(self):
        try:
            movement = (
                choice(
                    [
                        0,
                        (self.paddle.position.y - self.ball.position.y)
                        / abs(self.paddle.position.y - self.ball.position.y),
                    ]
                )
                if random() > self.difficulty / 4
                else -(self.paddle.position.y - self.ball.position.y)
                / abs(self.paddle.position.y - self.ball.position.y)
            )
        except ZeroDivisionError:
            movement = choice([1, -1]) if random() > self.difficulty / 4 else 0
        except Exception as e:
            logger.error(e)

        self.paddle.move(movement)


def make_box(stdscr, width: float, height: float):
    stdscr.addstr(
        0,
        0,
        f"┌{'─' * (ceil((width - 2) / 2) - 1)}┬{'─' * (ceil((width - 2) / 2) - 1)}┐",
    )

    for _ in range(ceil((height - 4) / 2)):
        stdscr.addstr(
            _ * 2 + 1,
            0,
            f"│{' ' * (ceil((width - 2) / 2) - 1)}│{' ' * (ceil((width - 2) / 2) - 1)}│",
        )
        stdscr.addstr(_ * 2 + 2, 0, f"│{' ' * (width - 2)}│")
    stdscr.addstr(
        height - 3,
        0,
        f"│{' ' * (ceil((width - 2) / 2) - 1)}│{' ' * (ceil((width - 2) / 2) - 1)}│",
    )
    stdscr.addstr(
        height - 2,
        0,
        f"└{'─' * (ceil((width - 2) / 2) - 1)}┴{'─' * (ceil((width - 2) / 2) - 1)}┘",
    )


def generate_playing_area(stdscr):
    width, height = get_terminal_size()

    width = width if width % 2 == 1 else width - 1
    height = height if height % 2 == 0 else height - 1

    make_box(stdscr, width, height)
    return width, height


def generate_paddle(stdscr, paddle: Paddle):
    for _ in range(paddle.length):
        stdscr.addstr(
            round(paddle.position.y) - ceil(paddle.length / 2) + 1 + _,
            paddle.position.x,
            " ",
            curses.A_REVERSE,
        )


def write_scores(stdscr, SCORE_POSITION: Vector2, width: int):
    global player_score, opponent_score
    stdscr.addstr(
        SCORE_POSITION.y, ceil(width / 2) - SCORE_POSITION.x, str(player_score)
    )
    stdscr.addstr(
        SCORE_POSITION.y, ceil(width / 2) - 3 + SCORE_POSITION.x, str(opponent_score)
    )


def draw(
    stdscr,
    ball: Ball,
    paddles: list[Paddle],
    score_pos: Vector2,
    width: int,
    stdinfo: list[Stdinfo],
):
    try:
        generate_playing_area(stdscr)
        stdscr.addstr(
            round(ball.position.y), round(ball.position.x), " ", curses.A_REVERSE
        )
        for _ in paddles:
            generate_paddle(stdscr, _)
        write_scores(stdscr, score_pos, width)
        for _ in stdinfo:
            _.write(stdscr)
        stdscr.refresh()

    except curses.error as ce:
        logger.critical(ce)
    except Exception as e:
        logger.error(e)


def update_paddle_movement(paddle: Paddle):
    movement = detect_keypress()
    paddle.move(movement)


def detect_keypress():
    if is_pressed("up") or is_pressed("w") or is_pressed("left") or is_pressed("a"):
        return -1

    elif (
        is_pressed("down") or is_pressed("s") or is_pressed("right") or is_pressed("d")
    ):
        return 1

    else:
        return 0


def movement(player_paddle: Paddle, enemyAI: EnemyAI):
    update_paddle_movement(player_paddle)
    enemyAI.move_paddle()


def ball_start(
    stdscr,
    ball: Ball,
    paddles_list: list[Paddle],
    score_position: Vector2,
    width: int,
    bounds: Vector2,
    enemyAI: EnemyAI,
):
    info = []
    start_time = time()
    while time() - start_time < 4:
        if time() - start_time < 1:
            info.append(Stdinfo("3", Vector2(ceil(bounds.x / 2), ceil(bounds.y / 5))))
        elif time() - start_time < 2:
            info.append(Stdinfo("2", Vector2(ceil(bounds.x / 2), ceil(bounds.y / 5))))
        elif time() - start_time < 3:
            info.append(Stdinfo("1", Vector2(ceil(bounds.x / 2), ceil(bounds.y / 5))))
        else:
            info.append(Stdinfo("GO!", Vector2(ceil(bounds.x / 2), ceil(bounds.y / 5))))

        movement(paddles_list[0], enemyAI)

        draw(
            stdscr,
            ball,
            paddles_list,
            score_position,
            width,
            info,
        )


def main_game_loop(
    start_time: float,
    FRAMERATE: int,
    ball: Ball,
    player_paddle: Paddle,
    enemyAI: EnemyAI,
):
    if start_time + 1 / FRAMERATE <= time():
        start_time = time()

        movement(player_paddle, enemyAI)

        ball.move()

    return start_time


def quit_game():
    global game_end
    while True and not game_end:
        if is_pressed("q"):
            break


def main(stdscr):
    global std
    std = stdscr

    curses.curs_set(0)
    stdscr.keypad(True)
    curses.noecho()
    stdscr.nodelay(True)
    curses.cbreak()
    stdscr.clear()

    with open(config_file_path, "r") as file:
        config = load(file)

    WIDTH, HEIGHT = generate_playing_area(stdscr)

    PLAYING_WIDTH = ceil((WIDTH - 2) / 2) - 1
    PLAYING_HEIGHT = HEIGHT - 3
    BOUNDS = Vector2(WIDTH, PLAYING_HEIGHT)

    PADDLE_LENGTH_MODIFIER = config["paddle_length_modifier"]
    PADDLE_SPEED = config["paddle_speed"]
    PADDLE_LENGTH = (
        ceil(PLAYING_HEIGHT * PADDLE_LENGTH_MODIFIER)
        if ceil(PLAYING_HEIGHT * PADDLE_LENGTH_MODIFIER) % 2 == 1
        else ceil(PLAYING_HEIGHT * PADDLE_LENGTH_MODIFIER) - 1
    )

    PADDLE_X_POS = ceil(PLAYING_WIDTH * 0.2)
    PADDLE_Y_POS = ceil(PLAYING_HEIGHT / 2)

    ENEMY_DIFFICULTY = config["enemy_difficulty"]
    BEST_OF = config["score_condition"]

    BALL_SPEED = config["ball_speed"]
    FRAMERATE = config["framerate"]

    global player_score, opponent_score, scored, info, game_end
    player_score = 0
    opponent_score = 0
    scored = False
    game_end = False
    info = []

    player_paddle = Paddle(
        PADDLE_LENGTH,
        Vector2(PADDLE_X_POS, PADDLE_Y_POS),
        1,
        PADDLE_SPEED,
        BOUNDS,
    )
    opponent_paddle = Paddle(
        PADDLE_LENGTH,
        Vector2(WIDTH - PADDLE_X_POS, PADDLE_Y_POS),
        -1,
        PADDLE_SPEED,
        BOUNDS,
    )
    PADDLES_LIST = [player_paddle, opponent_paddle]

    ball = Ball(
        Vector2(ceil(WIDTH / 2) - 1, ceil(HEIGHT / 2)),
        Vector2(0, 0),
        BOUNDS,
        BALL_SPEED,
        PADDLES_LIST,
    )
    ball.target_paddle()
    enemyAI = EnemyAI(ENEMY_DIFFICULTY, opponent_paddle, ball)

    SCORE_POSITION = Vector2(ceil(WIDTH / 16), ceil(HEIGHT / 4))

    draw(stdscr, ball, PADDLES_LIST, SCORE_POSITION, WIDTH, info)

    with concurrent.futures.ThreadPoolExecutor() as executor:

        quit_thread = executor.submit(quit_game)

        start_time = time()

        logger.info("Main Loop Started")

        ball_start(stdscr, ball, PADDLES_LIST, SCORE_POSITION, WIDTH, BOUNDS, enemyAI)

        while player_score < BEST_OF and opponent_score < BEST_OF:
            while True:

                try:
                    start_time = main_game_loop(
                        start_time, FRAMERATE, ball, player_paddle, enemyAI
                    )

                    if scored:
                        logger.info("Scored - Process Terminated")
                        break

                    if quit_thread.done():
                        logger.info("Quit Detected - Process Terminated")
                        break

                    draw(
                        stdscr,
                        ball,
                        PADDLES_LIST,
                        SCORE_POSITION,
                        WIDTH,
                        info,
                    )

                except Exception as e:
                    logger.error(e)

            if quit_thread.done():
                logger.info("Quit Detected - Process Terminated")
                break

            if scored:
                ball.reset()
                draw(
                    stdscr,
                    ball,
                    PADDLES_LIST,
                    SCORE_POSITION,
                    WIDTH,
                    info,
                )

                if player_score == BEST_OF or opponent_score == BEST_OF:
                    info = []
                    sleep(1)
                    break

                sleep(3)

                logger.info("Finished Cooldown")
                info = []
                scored = False

                ball_start(
                    stdscr, ball, PADDLES_LIST, SCORE_POSITION, WIDTH, BOUNDS, enemyAI
                )

        if player_score == BEST_OF:
            info.append(
                Stdinfo(
                    "Player Wins!",
                    Vector2(ceil(BOUNDS.x / 2), ceil(BOUNDS.y / 5)),
                )
            )
            logger.info("Player Win")
        elif opponent_score == BEST_OF:
            info.append(
                Stdinfo(
                    "You Lose...",
                    Vector2(ceil(BOUNDS.x / 2), ceil(BOUNDS.y / 5)),
                )
            )
            logger.info("Player Lose")

        draw(
            stdscr,
            ball,
            PADDLES_LIST,
            SCORE_POSITION,
            WIDTH,
            info,
        )

        sleep(3)
        game_end = True


if __name__ == "__main__":
    curses.wrapper(main)
