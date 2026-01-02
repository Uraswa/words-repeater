import datetime
import json
import random
import re
import numpy as np
from openai import OpenAI

from flask import Flask, render_template, request
import os.path
from flask_cors import CORS, cross_origin

import asyncpg
app = Flask(__name__)
cors = CORS(app) # allow CORS for all domains on all routes.

with open("config.json", 'r') as config_file:
    config = json.loads(config_file.read())

def _selectRepeatWords(words : list):

    random.shuffle(words)
    filtered_words = list(filter(lambda x: x['nextRepeatTime'] < datetime.datetime.now(), words))

    words2repeat = []
    for word in filtered_words:
        for w2r in words2repeat:
            if w2r['word'] == word['word']: break
        else:
            words2repeat.append(word)
        if len(words2repeat) == config['WordsPerTry']:
            return words2repeat
    return words2repeat


def _generateFirstStage(words, words2repeat):
    wordsrepeat = [w["word"] for w in words2repeat]
    words = list(filter(lambda x: x["word"] not in wordsrepeat, words))

    for w in words:
        w['nextRepeatTime'] = 0

    for w in words2repeat:
        w['nextRepeatTime'] = 0

    if len(words) == 0 or len(words2repeat) == 0:
        return []

    stage1 = []
    for w in words2repeat:

        options = []
        if "partOfSpeech" in w:
            wordsWithSamePartOfSpeech = list(filter(lambda x: "partOfSpeech" in x and x["partOfSpeech"] == w["partOfSpeech"], words))
            if (w["partOfSpeech"] == "v"
                or w["partOfSpeech"] == "n"
                or  w["partOfSpeech"] == "adj"
                or w["partOfSpeech"] == "adv") and len(wordsWithSamePartOfSpeech) >= 3:
                options = random.sample(wordsWithSamePartOfSpeech, 3)
            else:
                options = random.sample(words, 3)
        else:
            options = random.sample(words, 3)

        insert_index = random.randint(0, 3)

        options.insert(insert_index, w)

        stage1.append({
            "translated": w["translation"],
            "options": options,
            "word": w
        })

    return stage1


def _checkDatabase():
    if not os.path.isfile("database.json"):
        _createDatabase()


def _createDatabase():
    f = open("database.json", "w", encoding="utf-8")
    f.write(json.dumps([]))
    f.close()


async def _loadDatabase():
    """
    Асинхронная загрузка данных с использованием asyncpg
    """
    try:
        # Подключение к базе данных
        conn = await asyncpg.connect(
            database="English",
            user="nice",
            password="nice",
            host="localhost",
            port=5432
        )

        # Выполнение запроса
        rows = await conn.fetch("SELECT * FROM words")

        # Преобразование в список словарей
        words = []
        for row in rows:
            wordDict = dict(row)
            words.append({
                "wordId": wordDict["word_id"],
                "nextRepeatTime": wordDict["nextrepeattime"],
                "repeatIndex": wordDict["repeatindex"],
                "word": wordDict["word"],
                "translation": wordDict["translation"],
                "example": json.loads(wordDict["example"]) if wordDict["example"] else None,
                "partOfSpeech": wordDict["partofspeech"],
                "weight": wordDict["weight"]
            })

        await conn.close()
        return words

    except Exception as e:
        print(f"Ошибка: {e}")
        return []


async def _updateWordsInDatabaseAndSave(words2update, wordsInDatabase, doNotChangeRepeatTimes = False, doNotIncreaseRepeatIndex = False):
    conn = await asyncpg.connect(
        database="English",
        user="nice",
        password="nice",
        host="localhost",
        port=5432
    )

    for word in words2update:
        val = "someval"
        if type(words2update) == dict:
            val = words2update[word]

        if type(val) == bool:
            # сохранение результата из повторения

            for w in wordsInDatabase:
                if w["wordId"] == int(word):
                    wordDb = w

                    # Обновление веса в зависимости от результата
                    if not val:  # Неудача
                        wordDb["repeatIndex"] = 1
                        wordDb["weight"] = min(
                            1 + wordDb.get("weight", config['text_generation']['default_weight']) *
                            config['text_generation']['weight_increase_fail'],
                            config['text_generation']['max_weight']
                        )
                    else:  # Успех
                        if not doNotIncreaseRepeatIndex:
                            wordDb["repeatIndex"] = int(wordDb["repeatIndex"]) + 1
                        wordDb["weight"] = max(
                            wordDb.get("weight", config['text_generation']['default_weight']) *
                            config['text_generation']['weight_decrease_success'],
                            config['text_generation']['min_weight'])

                    if not doNotChangeRepeatTimes:
                        wordDb["nextRepeatTime"] = _getRepeatDateFromRepeatIndex(wordDb["repeatIndex"])
                    await conn.fetchval(
                        "UPDATE words SET repeatindex=$1, nextrepeattime=$2 WHERE word_id=$3",
                        wordDb["repeatIndex"], wordDb["nextRepeatTime"], wordDb["wordId"])

                    await conn.fetchval(
                        "INSERT INTO words_history (word_id, repeatindex, repeatdate) VALUES ($1, $2, NOW())",
                        wordDb["wordId"], wordDb["repeatIndex"])

                    break

        else:
            wordsInDatabase.append({
                "repeatIndex": 0,
                "translation": word["translation"],
                "word": word["word"],
                "nextRepeatTime": 0,
                "example": word["example"],
                "partOfSpeech": word["partOfSpeech"].replace(".", "")
            })

            await conn.fetchval("INSERT INTO words (translation, partofspeech, word, example, nextrepeattime) VALUES ($1, $2, $3, $4, NOW())", word["translation"], word["partOfSpeech"], word["word"], word["example"])

    await conn.close()


def _getRepeatDateFromRepeatIndex(repeatIndex):
    days = 0
    if repeatIndex == 0:
        days = 0
    elif repeatIndex == 1:
        days = 1
    elif repeatIndex == 2:
        days = 2
    elif repeatIndex == 3:
        days = 3
    elif repeatIndex == 4:
        days = 7
    elif repeatIndex == 5:
        days = 14
    else:
        days = 14

    # Получаем текущую дату и время
    current_date = datetime.datetime.now()
    # Добавляем нужное количество дней
    repeat_date = current_date + datetime.timedelta(days=days)

    return repeat_date


def _checkInput(words):
    # words_to_add = list()
    # any_word_added = False
    #
    # if not os.path.isfile("database.json"):
    #     return
    #
    # with open("input.txt", encoding="utf-8") as f:
    #     for l in f:
    #         splitted = l.split("=")
    #         if len(splitted) < 2:
    #             continue
    #
    #         word = splitted[0]
    #
    #         partOfSpeech = ""
    #         partOfSpeechMatch = re.search(r'\([A-Za-z]+\)', word)
    #         if partOfSpeechMatch:
    #             partOfSpeech = partOfSpeechMatch.group()
    #             word = word.replace(partOfSpeech, "")
    #             partOfSpeech = partOfSpeech.replace("(", "").replace(")", "")
    #
    #
    #         word = word.strip()
    #         word = word.lower()
    #         transAndExample = splitted[1].split(";")
    #
    #         translation = transAndExample[0]
    #         if len(transAndExample) > 1:
    #             example = transAndExample[1:]
    #         else:
    #             example = []
    #
    #         words_to_add.append({
    #             "word": word,
    #             "translation": translation,
    #             "example": example,
    #             "partOfSpeech": partOfSpeech
    #         })
    #         any_word_added = True
    #
    # with open("input.txt", "w", encoding="utf-8") as f:
    #     f.write("")
    #
    # if any_word_added:
    #     _updateWordsInDatabaseAndSave(words_to_add, words)
    pass


@app.route('/repeatWords', methods=['POST', 'GET'])
async def repeatWords():  # put application's code here

    _checkDatabase()
    words = await _loadDatabase()

    if request.method == 'POST':
        json_data = json.loads(request.get_data().decode('utf-8'))
        await _updateWordsInDatabaseAndSave(
            json_data["resultState"],
            words,
            json_data["decreaseRepeatIndexOnly"] if "decreaseRepeatIndexOnly" in json_data else False,
            json_data["decreaseRepeatIndexOnly"] if "decreaseRepeatIndexOnly" in json_data else False
        )

        return json.dumps({"success": True})

    _checkInput(words)

    words2repeat = _selectRepeatWords(words)

    firstStage = _generateFirstStage(words, words2repeat)

    res = json.dumps({
        "firstStage": firstStage,
        "words": words2repeat
    })
    print(res)
    return res

@app.route('/generate_text', methods=['POST'])
async def generate_text():  # put application's code here

    _checkDatabase()
    words = await _loadDatabase()

    """
        Генерирует текст с использованием изучаемых слов через DeepSeek API
        """
    # Get generation settings from request
    json_data = json.loads(request.get_data().decode('utf-8'))

    text_length = json_data.get('textLength', 250)  # default 250 words
    level = json_data.get('level', 'B1')  # default B1
    style = json_data.get('style', 'повествовательный')
    text_type = json_data.get('textType', 'общий')
    topic = json_data.get('topic', '')  # optional topic

    # Выбираем слова с наибольшим весом
    config = dict()
    with open("config.json") as f:
        config = json.loads(f.read())

    probabilities = []
    ids = set()
    su = 0
    for w in words:
        ids.add(w['wordId'])
        su += w.get('weight', 1.0)

    for w in words:
        probabilities.append(w.get('weight', 1.0) / (su))

    selected_words = np.random.choice(words, size=10, p=probabilities, replace=False)
    EXACT_MEANING = False

    def returnWordString(w):
        res = ''
        res += w['word']
        if EXACT_MEANING:
            res += w['translation'] + "|"
        return res

    top_words = [returnWordString(w) for w in selected_words]

    if not top_words:
        return json.dumps({"success": False, "error": "Недостаточно слов для генерации текста."}), 400

    words_formated = ",".join(top_words)

    # Build prompt based on settings
    level_descriptions = {
        'A1': 'начальный уровень (A1 - Elementary), используя простые конструкции и базовую лексику',
        'A2': 'элементарный уровень (A2 - Pre-Intermediate), используя несложные конструкции',
        'B1': 'средний уровень (B1 - Intermediate), используя разнообразные конструкции',
        'B2': 'уровень выше среднего (B2 - Upper-Intermediate), используя сложные конструкции',
        'C1': 'продвинутый уровень (C1 - Advanced), используя продвинутую лексику и сложные конструкции',
        'C2': 'профессиональный уровень (C2 - Proficiency), используя богатую лексику и сложнейшие конструкции'
    }

    level_desc = level_descriptions.get(level, level_descriptions['B1'])

    topic_part = f" на тему '{topic}'" if topic else " на любую интересную тему"
    style_part = f" в {style} стиле"
    type_part = f" Тип текста: {text_type}."

    prompt = f"""
    Сгенерируй осмысленный и интересный, грамматически правильный и связный текст на английском языке уровня {level_desc}{topic_part}{style_part}. {type_part}
    Длина текста должна быть около {text_length} слов.

    Текст предназначен для использования в качестве тестового задания, где студенту нужно вставить на место пропуска слово из списка вариантов.
    Текст должен естественным образом включать минимум 10, максимум 15 случайных слов из следующего списка: {words_formated}.

    В дальнейшем я самостоятельно обработаю этот текст и вместо слов, которые ты вставил, сделаю пропуски, поэтому необходимо генерировать текст так, чтобы можно было однозначно определить какое слово пропущено. Не должно быть двойственных ситуаций, когда невозможно точно определить какое слово пропущено.

    Ответ верни как валидный JSON, чтобы его можно было распарсить без всяких манипуляций. НИКАКОГО СЛОВА JSON, символов ` в начале текста быть не должно!!!! Только валидный json объект с такими полями:
    "Header": Заголовок текста (string)
    "Text": Текст (string),
    "RightAnswers": "Массив правильных ответов в порядке, в котором они встречаются в тексте. Слова должны быть в том же виде, в каком они встречаются в тексте (например, если слово в тексте в прошедшем, то здесь оно тоже должно быть в прошедшем)" string[],
    "RightIndeces": Массив индексов правильных ответов в порядке, в котором они расположены в списке, отчет начинается с нуля. int[]
    """

    print("Prompt:", prompt)

    client = OpenAI(api_key='sk-c2efe9ecf3044357b7c0272efaf39d51', base_url="https://api.deepseek.com")

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system",
             "content": "Ты опытный преподаватель английского языка, поэтому ищешь индивидуальный подход к каждому ученику, анализируя его сильные и слабые стороны, предлагаешь такие задание, чтобы изучение английского шло максимально эффективно."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=text_length * 2,
        temperature=config['text_generation']['temperature'],
        stream=False
    )

    content = response.choices[0].message.content.replace("`", "").replace("json", "").replace("JSON", "")
    parsed = json.loads(content)

    text = parsed['Text']
    identifiers = []

    iteration = 0
    for ans in parsed['RightAnswers']:
        text = text.replace(ans, '<>', 1)
        word = selected_words[parsed['RightIndeces'][iteration]]
        identifiers.append(word['wordId'])
        iteration += 1

    wordsInText = [w for w in parsed['RightAnswers']]
    random.shuffle(wordsInText)
    parsed['answers'] = parsed['RightAnswers']
    parsed['words'] = wordsInText
    parsed['text'] = text
    parsed['Identifiers'] = identifiers

    del parsed['RightAnswers']
    del parsed['RightIndeces']
    del parsed['Text']

    return parsed

@app.route('/checkText', methods=['POST'])
async def check_text():
    json_data = json.loads(request.get_data().decode('utf-8'))
    text = json_data['text']
    rightAnswers = json_data['rightAnswers']
    userAnswers = json_data['userAnswers']

    prompt = f"""
        Тебе нужно проверить тестовое задание по английскому языку, в котором нужно прочитать текст и заполнить пропущенные слова, выбрав правильный вариант из списка слов.
        Вот тестовое задание, пропуски отмечены символами <>: {text}
        Вот правильные ответы по порядку для каждого пропуска: {",".join(rightAnswers)}
        Вот ответы, данные пользователем по порядку для каждого пропуска: {",".join(userAnswers)}
        Проанализируй текст, правильные ответы и ответы пользователя, если пользователь ошибся, то объясни в чем заключается его ошибка. Каждую ошибку отделяй символом \n (начинай обозревать с новой строки.) Если слово в ошибке используется во фразовом глаголе, либо устойчивом выражении обязательно это обозначь, а также объясни смысл этого выражения/фразового глагола. Обращай внимание на грамматику, если вставка слова нелогична из-за грамматических норм, объясняй почему так. Не делай объяснение слишком сухим, не ограничивайся только переводом, в то же время, не делай объяснение слишком громоздким. В твоем ответе не должно быть вводных фраз, похвал, только обзор ошибок.
"""

    print("Prompt:", prompt)

    client = OpenAI(api_key='sk-c2efe9ecf3044357b7c0272efaf39d51', base_url="https://api.deepseek.com")

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system",
             "content": "Ты опытный преподаватель английского языка, поэтому ищешь индивидуальный подход к каждому ученику, анализируя его сильные и слабые стороны, предлагаешь такие задание, чтобы изучение английского шло максимально эффективно."},
            {"role": "user", "content": prompt},
        ],
        temperature=config['text_generation']['temperature'],
        stream=False
    )

    content = response.choices[0].message.content
    return {
        "ai_explain": content
    }

@app.route('/getWords', methods=['GET'])
async def get_words():
    _checkDatabase()
    words = await _loadDatabase()

    return words


@app.route('/addWord', methods=['POST'])
async def add_word():
    json_data = json.loads(request.get_data().decode('utf-8'))

    word = json_data.get('word', '').strip().lower()
    translation = json_data.get('translation', '').strip()
    examples = json_data.get('examples', [])

    if not word or not translation:
        return json.dumps({"success": False, "error": "Word and translation are required"}), 400

    try:
        conn = await asyncpg.connect(
            database="English",
            user="nice",
            password="nice",
            host="localhost",
            port=5432
        )

        # Check if word already exists
        existing = await conn.fetchrow("SELECT word_id FROM words WHERE word = $1", word)
        if existing:
            await conn.close()
            return json.dumps({"success": False, "error": "Word already exists"}), 400

        # Insert new word
        await conn.fetchval(
            "INSERT INTO words (word, translation, example, nextrepeattime, repeatindex, weight) VALUES ($1, $2, $3, NOW(), 0, $4)",
            word,
            translation,
            json.dumps(examples) if examples else None,
            config['text_generation']['default_weight']
        )

        await conn.close()
        return json.dumps({"success": True})

    except Exception as e:
        print(f"Error adding word: {e}")
        return json.dumps({"success": False, "error": str(e)}), 500


@app.route('/deleteWord/<int:word_id>', methods=['DELETE'])
async def delete_word(word_id):
    try:
        conn = await asyncpg.connect(
            database="English",
            user="nice",
            password="nice",
            host="localhost",
            port=5432
        )

        # Check if word exists
        existing = await conn.fetchrow("SELECT word_id FROM words WHERE word_id = $1", word_id)
        if not existing:
            await conn.close()
            return json.dumps({"success": False, "error": "Word not found"}), 404

        # Delete from history first (foreign key constraint)
        await conn.execute("DELETE FROM words_history WHERE word_id = $1", word_id)

        # Delete word
        await conn.execute("DELETE FROM words WHERE word_id = $1", word_id)

        await conn.close()
        return json.dumps({"success": True})

    except Exception as e:
        print(f"Error deleting word: {e}")
        return json.dumps({"success": False, "error": str(e)}), 500


@app.route('/getStatistics', methods=['GET'])
async def get_statistics():
    try:
        conn = await asyncpg.connect(
            database="English",
            user="nice",
            password="nice",
            host="localhost",
            port=5432
        )

        # Total repetitions
        total_reps = await conn.fetchval("SELECT COUNT(*) FROM words_history")

        # Repetitions by day (last 30 days)
        reps_by_day = await conn.fetch("""
            SELECT
                DATE(repeatdate) as date,
                COUNT(*) as count
            FROM words_history
            WHERE repeatdate >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(repeatdate)
            ORDER BY date
        """)

        # Top repeated words
        top_words = await conn.fetch("""
            SELECT
                w.word,
                w.translation,
                COUNT(*) as repetitions
            FROM words_history wh
            JOIN words w ON wh.word_id = w.word_id
            GROUP BY w.word_id, w.word, w.translation
            ORDER BY repetitions DESC
            LIMIT 10
        """)

        # Distribution by repeat index
        index_distribution = await conn.fetch("""
            SELECT
                repeatindex,
                COUNT(*) as count
            FROM words_history
            GROUP BY repeatindex
            ORDER BY repeatindex
        """)

        # Current streak (consecutive days)
        streak_data = await conn.fetch("""
            SELECT DISTINCT DATE(repeatdate) as date
            FROM words_history
            ORDER BY date DESC
        """)

        # Calculate streak
        current_streak = 0
        if streak_data:
            today = datetime.datetime.now().date()
            for i, row in enumerate(streak_data):
                expected_date = today - datetime.timedelta(days=i)
                if row['date'] == expected_date:
                    current_streak += 1
                else:
                    break

        # Total unique words practiced
        unique_words = await conn.fetchval("""
            SELECT COUNT(DISTINCT word_id) FROM words_history
        """)

        # Average repetitions per day (last 30 days)
        avg_per_day = await conn.fetchval("""
            SELECT AVG(daily_count)::FLOAT
            FROM (
                SELECT DATE(repeatdate), COUNT(*) as daily_count
                FROM words_history
                WHERE repeatdate >= NOW() - INTERVAL '30 days'
                GROUP BY DATE(repeatdate)
            ) as daily_stats
        """)

        # Upcoming repetitions by day (next 30 days)
        upcoming_reps = await conn.fetch("""
            SELECT
                DATE(CASE WHEN nextrepeattime < NOW() THEN NOW() ELSE nextrepeattime END) as date,
                COUNT(*) as count,
                ARRAY_AGG(word ORDER BY word) as words
            FROM words
            WHERE DATE(nextrepeattime) < CURRENT_DATE + INTERVAL '30 days'
            GROUP BY DATE(CASE WHEN nextrepeattime < NOW() THEN NOW() ELSE nextrepeattime END)
            ORDER BY date
        """)

        await conn.close()

        return json.dumps({
            "totalRepetitions": total_reps,
            "repetitionsByDay": [{"date": str(row['date']), "count": row['count']} for row in reps_by_day],
            "topWords": [{"word": row['word'], "translation": row['translation'], "repetitions": row['repetitions']} for row in top_words],
            "indexDistribution": [{"index": row['repeatindex'], "count": row['count']} for row in index_distribution],
            "currentStreak": current_streak,
            "uniqueWords": unique_words,
            "averagePerDay": round(avg_per_day, 1) if avg_per_day else 0,
            "upcomingRepetitions": [{"date": str(row['date']), "count": row['count'], "words": row['words']} for row in upcoming_reps]
        })

    except Exception as e:
        print(f"Error getting statistics: {e}")
        return json.dumps({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    app.run()
