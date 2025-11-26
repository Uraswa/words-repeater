import json
import random
import re

from flask import Flask, render_template, request
import os.path
import time

import asyncpg
app = Flask(__name__)

with open("config.json", 'r') as config_file:
    config = json.loads(config_file.read())

def _selectRepeatWords(words : list):

    random.shuffle(words)
    filtered_words = list(filter(lambda x: x['nextRepeatTime'] < int(time.time()), words))

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


def _loadDatabase():
    with open("database.json", "r", encoding="utf-8") as f:
        words = json.loads(f.read())
        return words


def _updateWordsInDatabaseAndSave(words2update, words):
    for word in words2update:
        val = "someval"
        if type(words2update) == dict:
            val = words2update[word]

        if type(val) == bool:
            # сохранение результата из повторения

            for w in words:
                if w["word"] == word:
                    wordDb = w

                    if not val:
                        wordDb["repeatIndex"] = 1
                    else:
                        wordDb["repeatIndex"] = int(wordDb["repeatIndex"]) + 1

                    wordDb["nextRepeatTime"] = _getRepeatDateFromRepeatIndex(wordDb["repeatIndex"])
                    break

        else:
            words.append({
                "repeatIndex": 0,
                "translation": word["translation"],
                "word": word["word"],
                "nextRepeatTime": 0,
                "example": word["example"],
                "partOfSpeech": word["partOfSpeech"].replace(".", "")
            })
    with open("database.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(words, indent=4))


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

    current_time = int(time.time())
    current_time += days * 86400

    return current_time


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


@app.route('/', methods=['POST', 'GET'])
def hello_world():  # put application's code here

    _checkDatabase()
    words = _loadDatabase()

    if request.method == 'POST':
        json_data = json.loads(request.get_data().decode('utf-8'))
        _updateWordsInDatabaseAndSave(json_data, words)

        return json.dumps({"success": True})

    _checkInput(words)

    words2repeat = _selectRepeatWords(words)

    firstStage = _generateFirstStage(words, words2repeat)

    return render_template("index.html", data={
        "firstStage": firstStage,
        "words": words2repeat
    })


if __name__ == '__main__':
    app.run()
