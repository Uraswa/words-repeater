import datetime
import json
import random
import re

from flask import Flask, render_template, request
import os.path
import time
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
    words_to_add = list()
    any_word_added = False

    if not os.path.isfile("database.json"):
        return

    with open("input.txt", encoding="utf-8") as f:
        for l in f:
            splitted = l.split("=")
            if len(splitted) < 2:
                continue

            word = splitted[0]

            partOfSpeech = ""
            partOfSpeechMatch = re.search(r'\([A-Za-z]+\)', word)
            if partOfSpeechMatch:
                partOfSpeech = partOfSpeechMatch.group()
                word = word.replace(partOfSpeech, "")
                partOfSpeech = partOfSpeech.replace("(", "").replace(")", "")


            word = word.strip()
            word = word.lower()
            transAndExample = splitted[1].split(";")

            translation = transAndExample[0]
            if len(transAndExample) > 1:
                example = transAndExample[1:]
            else:
                example = []

            words_to_add.append({
                "word": word,
                "translation": translation,
                "example": example,
                "partOfSpeech": partOfSpeech
            })
            any_word_added = True

    with open("input.txt", "w", encoding="utf-8") as f:
        f.write("")

    if any_word_added:
        _updateWordsInDatabaseAndSave(words_to_add, words)


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

    return json.dumps({
        "firstStage": firstStage,
        "words": words2repeat
    })

@app.route('/generate_text', methods=['POST', 'GET'])
async def generate_text():  # put application's code here

    _checkDatabase()
    words = await _loadDatabase()

    """
        Генерирует текст с использованием изучаемых слов через DeepSeek API
        """
    # Выбираем слова с наибольшим весом

    from openai import OpenAI

    config = dict()
    with open("config.json") as f:
        config = json.loads(f.read())

    weights = []
    ids = set()
    for w in words:
        ids.add(w['wordId'])
        weights.append(w.get('weight', 1.0))

    selected_words = random.choices(words, weights, k=20)

    EXACT_MEANING = False

    def returnWordString(w):
        res = ''
        res += w['word'] + "|"
        if EXACT_MEANING:
            res += w['translation'] + "|"
        res += str(w['wordId'])
        return res

    top_words = [returnWordString(w) for w in selected_words]

    if not top_words:
        return "Недостаточно слов для генерации текста."

    words_formated = ",\n".join(top_words)
    prompt = f"""
    Сгенерируй осмысленный и интересный текст на английском языке длиной около 200-250 слов, чтобы использовать его в качестве тестового задания, где студенту нужно вставить на место пропуска слово из списка вариантов.
    Тема текста может быть любой: рассказ, статья, описание и т.д.
    Текст должен естественным образом включать минимум 10, максимум 15 случайных слов из следующего списка:\n{words_formated}.
    В местах, куда ты вставил слова из списка, сделай вот такой пропуск: ПРОПУСК. Необходимо генерировать текст так, чтобы можно было определить какое слово пропущено. Не должно быть
    двойственных ситуаций, когда невозможно точно определить какое слово пропущно.
    Каждое слово состоит из след. составляющих: само слово|{'какое значение имеет слово|' if EXACT_MEANING else ''}идентефикатор слова. 
    {'Если слово в английском языке имеет несколько значений, то желательно, чтобы в тексте смысл слова был таким же, либо похожим на значение указанное у этого слова в списке слов.' if EXACT_MEANING else ''}
    Текст должен быть на уровне intermediate английского, грамматически правильным и связным.
    Ответ верни как валидный JSON,чтобы его можно было распарсить без всяких манипуляций. НИКАКОГО СЛОВА JSON, символов ` в начале текста быть не должно!!!! Только валидный json объект такого с такими полями:
    "Header": Заголовок(string)
    "Text": Текст(string),
    "Identifiers": массив идентефикаторов слов, которые ты вставил в текст из списка, в порядке их вставки(int[])  
    больше в ответе ничего лишнего быть не должно!
    идентефикаторов слов, которые ты вставил в текст из списка, в порядке их вставки, в формате identifier;identifier; больше в ответе ничего лишнего быть не должно!,
    "RightAnswers": "Массив правильных ответов в порядке, в котором они встречаются в тексте. Слова должны быть в том же виде, что они встречаются в тексте (например, если слово в тексте в прошедшем, то здесь оно тоже должно быть в прошедшем)" string[]
    """

    print("Prompt:", prompt)

    client = OpenAI(api_key='sk-417c2dc785a7445e93c0e9c0d33c1ac3', base_url="https://api.deepseek.com")

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system",
             "content": "Ты опытный преподаватель английского языка, поэтому ищешь индивидуальный подход к каждому ученику, анализируя его сильные и слабые стороны, предлагаешь такие задание, чтобы изучение английского шло максимально эффективно."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=config['text_generation']['max_length'],
        temperature=config['text_generation']['temperature'],
        stream=False
    )

    content = response.choices[0].message.content
    parsed = json.loads(content)

    text = parsed['Text']
    regex = r"\*\w+\*"
    matches = re.findall(regex, text)

    print(matches)
    wordsInText = []


    for m in matches:
        text = text.replace(m, '<>')
        wordsInText.append(m.replace('*', ''))

    index = 0
    for idn in parsed['Identifiers']:
        if idn not in ids:
            print(f"Слово {idn} не найдено.")

    parsed['words'] = wordsInText
    parsed['text'] = text
#     text = """The Hidden Cost of Progress
#
# In our modern world, the rapid *acquisition*;29 of new technologies and the constant *accumulation*;25 of material goods
# have become the norm. While this progress offers an *abundance*;14 of conveniences, it also presents an *acute*;30
# challenge to our environment. We must *adequately*;5 address the *adverse*;39 effects of our consumption. The
# *absence*;9 of *adequate*;4 environmental policies in many regions means that pollution continues to *accumulate*;23 in
# our air and water. It is crucial that we *adhere*;32 to sustainable principles and hold corporations *accountable*;21
# for their ecological impact. The *adoption*;41 of greener practices is no longer a choice but a necessity. We cannot
# remain *absent*;11 from this global conversation. Our natural world seems to *absorb*;13 our neglect, but there is a
# limit. We must act *accordingly*;18, ensuring that our pursuit of progress does not come at the cost of our planet's
# health."""
    return parsed



if __name__ == '__main__':
    app.run()
