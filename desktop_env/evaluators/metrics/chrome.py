import logging
import os
import re
import shutil
from itertools import product
from typing import Any, Dict, List, Union

import rapidfuzz.fuzz as fuzz
from bs4 import BeautifulSoup, Tag

from desktop_env.evaluators.metrics.utils import are_lists_equal, compare_urls

import nltk
nltk.download('punkt_tab')
from nltk.tokenize import word_tokenize
import collections
import urllib
import openai
from typing import Optional
from anthropic import AnthropicBedrock


# from desktop_env.evaluators.metrics.helper_functions import (
#     llm_fuzzy_match,
#     llm_ua_match,
# )

logger = logging.getLogger("desktopenv.metrics.chrome")

##### For WebArena #####
def clean_answer(s: str) -> str:
    s = s.strip()
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    elif s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s.lower()

def exact_match(ref: str, pred: str) -> float:
    return float(clean_answer(ref) == clean_answer(pred))

def must_include(ref: str, pred: str, tokenize: bool = False) -> float:
    clean_ref = clean_answer(ref)
    clean_pred = clean_answer(pred)
    # tokenize the answer if the ref is a single word
    # prevent false positive (e.g, 0)
    if (
        tokenize
        and len(clean_ref) == 1
        and len(word_tokenize(clean_ref)) == 1
    ):
        tok_pred = word_tokenize(clean_pred)
        return float(clean_ref in tok_pred)
    else:
        return float(clean_ref in clean_pred)

def generate_from_openai_chat_completion(
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    top_p: float,
    context_length: int,
    stop_token: Optional[str] = None,
) -> str:
    if "OPENAI_API_KEY" not in os.environ:
        raise ValueError(
            "OPENAI_API_KEY environment variable must be set when using OpenAI API."
        )
    # client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    from openai import AzureOpenAI
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_API_KEY"),
        api_version=os.getenv("AZURE_API_VERSION_FOR_FUZZY_MATCH"),
        azure_endpoint=os.getenv("AZURE_ENDPOINT_FOR_FUZZY_MATCH"),
    )

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stop=[stop_token] if stop_token else None,
    )

    answer: str = response.choices[0].message.content
    return answer

def generate_from_claude(
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    top_p: float,
    context_length: int,
    stop_token: Optional[str] = None,
) -> str:
    client = AnthropicBedrock(
        aws_access_key=os.getenv("AWS_ACCESS_KEY"),
        aws_secret_key=os.getenv("AWS_SECRET_KEY"),
        aws_region="us-west-2",
    )

    response = client.messages.create(
        model=model,  
        messages=messages,
        temperature=temperature, 
        max_tokens=max_tokens,
        top_p=top_p,
        stop_sequences=[stop_token] if stop_token else None
    )

    return response.content[0].text

def fuzzy_match(ref: str, pred: str, intent: str) -> float:
    """Check whether the prediction matches the reference with GPT4-turbo"""
    messages: list[dict[str, Any]] = []
    # construct the question to ask
    message = "Help a teacher to grade the answer of a student given a question. Keep in mind that the student may use different phrasing or wording to answer the question. The goal is to evaluate whether the answer is semantically equivalent to the reference answer.\n"
    message += "The student might be a computer use agent and the answer might be its own output log at different step. If so, you need to carefully review the output log at each step and identify if its log provide correct answer to the question.\n"
    message += f"question: {intent}\n"
    message += f"reference answer: {ref}\n"
    message += "all the string 'N/A' that you see is a special sequence that means 'not achievable'\n"
    message += f"student answer: {pred}\n"
    message += "Conclude the judgement by correct/incorrect/partially correct."

    # messages = [
    #     {"role": "system", "content": "You are a helpful assistant"},
    #     {"role": "user", "content": message},
    # ]
    messages = [
        {"role": "user", "content": "You are a helpful assistant. " + message}
    ]
    logger.info(f"llm fuzzy match: {messages}")

    # For OpenAI
    # response = generate_from_openai_chat_completion(
    #     model="gpt-4o-mini",
    #     messages=messages,
    #     temperature=0,
    #     max_tokens=768,
    #     top_p=1.0,
    #     context_length=0,
    # ).lower()

    # For claude
    response = generate_from_claude(
        model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        messages=messages,
        temperature=0,
        max_tokens=768,
        top_p=1.0,
        context_length=0,
    ).lower()

    logger.info(f"llm fuzzy match: {response}")
    if "partially correct" in response or "incorrect" in response:
        return 0.0
    else:
        assert "correct" in response
        return 1.0

def ua_match(ref: str, pred: str, intent: str) -> float:
    """Check whether the prediction matches the reference with GPT-turbo"""
    messages: list[dict[str, Any]] = []
    # construct the question to ask
    message = ""
    message += f"task: {intent}\n"
    message += f"actual unachievable reason: {ref}\n"
    message += f"reported unachievable reason: {pred}\n"
    message += (
        "The task described above is inherently unachievable due to the reason specified under 'actual unachievable reason'. "
        "An individual previously attempted this task and was unable to complete it. They provided a reason for their failure, "
        "which is listed under 'reported unachievable reason'. Your role is to review both the actual and reported reasons. "
        "Determine if the reported reason aligns with the actual reason, even if implicitly. "
        "If the stated reason is in line with the actual reason, respond with 'same'. Otherwise, respond with 'different'."
    )

    # messages = [
    #     {"role": "system", "content": "You are a helpful assistant"},
    #     {"role": "user", "content": message},
    # ]
    messages = [
        {"role": "user", "content": "You are a helpful assistant. " + message}
    ]

    logger.info(f"llm ua match: {messages}")

    # For OpenAI
    # response = generate_from_openai_chat_completion(
    #     model="gpt-4o-mini",
    #     messages=messages,
    #     temperature=0,
    #     max_tokens=768,
    #     top_p=1.0,
    #     context_length=0,
    # ).lower()

    # For claude
    response = generate_from_claude(
        model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        messages=messages,
        temperature=0,
        max_tokens=768,
        top_p=1.0,
        context_length=0,
    ).lower()

    logger.info(f"llm ua match: {response}")
    if "different" in response:
        return 0.0
    else:
        assert "same" in response
        return 1.0

def fuzzy_must_include(ref: str, pred: str, intent: str) -> float:
    """Check whether the prediction matches the reference with GPT4-turbo"""
    messages: list[dict[str, Any]] = []
    # construct the question to ask
    message = "Help a teacher to grade the answer of a student given a question. Keep in mind that the student may use different phrasing or wording to answer the question. The goal is to evaluate whether the answer includes the reference answer.\n"
    message += "The student might be a computer use agent and the answer might be its own output log at different step. If so, you need to carefully review the output log at each step and identify if its log provide correct answer to the question.\n"
    # message += f"question: {intent}\n"
    message += f"reference answer: {ref}\n"
    message += "all the string 'N/A' that you see is a special sequence that means 'not achievable'\n"
    message += f"student answer: {pred}\n"
    message += "Conclude the judgement by correct/incorrect."

    # messages = [
    #     {"role": "system", "content": "You are a helpful assistant"},
    #     {"role": "user", "content": message},
    # ]
    messages = [
        {"role": "user", "content": "You are a helpful assistant. " + message}
    ]
    logger.info(f"llm fuzzy match: {messages}")

    # For OpenAI
    # response = generate_from_openai_chat_completion(
    #     model="gpt-4o-mini",
    #     messages=messages,
    #     temperature=0,
    #     max_tokens=768,
    #     top_p=1.0,
    #     context_length=0,
    # ).lower()

    # For claude
    response = generate_from_claude(
        model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        messages=messages,
        temperature=0,
        max_tokens=768,
        top_p=1.0,
        context_length=0,
    ).lower()

    logger.info(f"llm fuzzy match: {response}")
    if "partially correct" in response or "incorrect" in response:
        return 0.0
    else:
        assert "correct" in response
        return 1.0

# For string_match
def is_string_match(res: str, rule: Dict[str, Any]) -> float:
    logger.info(f"Evaluate string match: {res}, {rule['reference_answers']}")

    score = 1.0
    for approach, value in rule["reference_answers"].items():
        if approach == "exact_match":
            score *= exact_match(value, res)

        elif approach == "must_include":
            assert isinstance(value, list)
            for must_value in value:
                score *= fuzzy_must_include(
                    ref=must_value,
                    pred=res,
                    intent=rule["intent"],
                )

        elif approach == "fuzzy_match":
            if value == "N/A":
                # if the instruction only asks the model to generate N/A when encountering an unachievable task
                # without more concrete reasons
                score *= exact_match(ref=value, pred=res)
                # if the instruction also asks the model to generate the reason why the task is unachievable
                # this should be the default as it will prevent false positive N/A`
                if score != 1:
                    score = 1.0 * ua_match(
                        intent=rule["intent"],
                        ref=rule["string_note"],
                        pred=res,
                    )
            else:
                assert isinstance(value, list)
                for reference in value:
                    score *= fuzzy_match(
                        ref=reference, pred=res, intent=rule["intent"]
                    )
    return score


# For url_match
def is_url_match(active_url: str, rule: Dict[str, Any]) -> float:
    logger.info(f"Evaluate url match: {active_url}, {rule['url']}")

    def clean_url(url: str) -> str:
        url = str(url)
        url = url.rstrip("/")
        return url

    def parse_url(url: str) -> tuple[str, dict[str, list[str]]]:
        """Parse a URL into its base, path, and query components."""
        parsed_url = urllib.parse.urlparse(url)
        base_path = parsed_url.netloc + parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)
        return base_path, query

    def parse_urls(
        urls: list[str],
    ) -> tuple[list[str], dict[str, set[str]]]:
        """Parse a list of URLs."""
        base_paths = []
        queries = collections.defaultdict(set)
        for url in urls:
            base_path, query = parse_url(url)
            base_paths.append(base_path)
            for k, v in query.items():
                queries[k].update(v)
        return base_paths, queries

    pred = clean_url(active_url)
    ref_urls = rule["url"].split(" |OR| ")
    ref_urls = [clean_url(url) for url in ref_urls]
    
    matching_rule = rule["matching_rule"]
    if matching_rule == "GOLD in PRED":
        ref_base_paths, ref_queries = parse_urls(ref_urls)
        pred_base_paths, pred_query = parse_url(pred)

        base_score = float(
            any(
                [
                    ref_base_path in pred_base_paths
                    for ref_base_path in ref_base_paths
                ]
            )
        )
        query_score = 1.0
        for k, possible_values in ref_queries.items():
            query_score *= float(
                any(
                    possible_ref_value in pred_query.get(k, [])
                    for possible_ref_value in possible_values
                )
            )
        score = base_score * query_score
        return score
        
    else:
        raise ValueError(f"Unknown matching rule: {matching_rule}")


# For program_html
def is_program_html_match(selected_elements: List, rule: Dict[str, Any]) -> float:
    logger.info(f"Evaluate program_html match: {selected_elements}, {rule['required_contents']}")

    required_contents = rule["required_contents"]
    if len(selected_elements) != len(required_contents):
        logger.error(f"Mismatch in lengths: selected_elements ({len(selected_elements)}) vs required_contents ({len(required_contents)})")
        return 0

    score = 1
    for ind, selected_element in enumerate(selected_elements):
        if "exact_match" in required_contents[ind]:
            contents = required_contents[ind]["exact_match"]
            cur_score = exact_match(
                ref=contents, pred=selected_element
            )
            score *= float(cur_score)
            # print(f"[exact match] {cur_score}, selected element: {selected_element}, required contents: {required_contents}")
        elif "must_include" in required_contents[ind]:
            contents = required_contents[ind]["must_include"]
            assert isinstance(contents, list)
            for content in contents:
                content_or = content.split(" |OR| ")
                cur_score = any(
                    [
                        fuzzy_must_include(
                            ref=content,
                            pred=selected_element,
                            intent=rule["intent"],
                        )
                        for content in content_or
                    ]
                )
                score *= float(cur_score)
                # print(f"[must include] {cur_score}, selected element: {selected_element}, required contents: {content_or}")
        else:
            raise ValueError(
                f"Unknown required_contents: {required_contents[ind].keys()}"
            )
            
    return score

##### For WebArena #####

def is_expected_active_tab(active_tab_info: Dict[str, str], rule: Dict[str, Any]) -> float:
    """
    Checks if the expected active tab is open in Chrome.
    """
    if not active_tab_info:
        return 0.

    match_type = rule['type']

    if match_type == "url":
        expected_url = rule['url']
        if isinstance(active_tab_info, Dict):
            actual_url = active_tab_info.get('url', None)
        else:
            actual_url = active_tab_info
        print("expected_url: {}".format(expected_url))
        print("actual_url: {}".format(actual_url))
        return 1 if compare_urls(expected_url, actual_url) else 0
    else:
        logger.error(f"Unknown type: {match_type}")
        return 0


# rules[expected] is a string-formatted regex
def is_expected_url_pattern_match(result, rules) -> float:
    """
    This function is used to search the expected pattern in the url using regex.
    result is the return value of function "activte_tab_info" or return value of function "get_active_url_from_accessTree"   
    """
    if not result:
        return 0.

    if type(result) == dict:
        result_url = result["url"]
        print("result url: {}".format(result_url))
    else:
        result_url = result
    # expect_regex = re.compile(rules["expected"])
    patterns = rules["expected"]
    print("expected_regex: {}".format(patterns))
    for pattern in patterns:
        match = re.search(pattern, result_url)
        print(match)
        if not match:
            return 0.
    return 1.


def is_expected_installed_extensions(installed_extensions, expected) -> float:
    print("installed_extensions: ")
    print(installed_extensions)
    expected_extensions = expected["expected"]

    # whether the expected extensions are installed
    set_expected_extensions = set(expected_extensions)
    set_installed_extensions = set(installed_extensions)

    if set_expected_extensions.issubset(set_installed_extensions):
        return 1.
    else:
        return 0.


def is_expected_tabs(open_tabs: List[Dict[str, str]], rule: Dict[str, Any]) -> float:
    """
    Checks if the expected tabs are open in Chrome.
    """

    match_type = rule['type']

    if match_type == "url":
        expected_urls = rule['urls']
        actual_urls = [tab['url'] for tab in open_tabs]
        return 1 if are_lists_equal(expected_urls, actual_urls, compare_urls) else 0
    else:
        logger.error(f"Unknown type: {match_type}")
        return 0
    

def check_tab_cnt(open_tabs: List[Dict[str, str]], rule: Dict[str, Any]) -> float:
    """
    Checks the tab count.
    """
    expected_cnt = rule["expected"]
    
    logger.info(f"expected cnt: {expected_cnt}")
    logger.info(f"result cnt: {len(open_tabs)}")
    logger.info(f"Open Tabs: {open_tabs}")
    if int(len(open_tabs)) >= expected_cnt:
        return 1
    else:
        return 0


def is_expected_bookmarks(bookmarks: List[str], rule: Dict[str, Any]) -> float:
    """
    Checks if the expected bookmarks are in Chrome.
    """
    if not bookmarks:
        return 0.
    elif rule['type'] == "bookmark_bar_folders_names":
        bookmark_bar_folders_names = [bookmark['name'] for bookmark in bookmarks['bookmark_bar']['children'] if
                                      bookmark['type'] == 'folder']
        return 1. if set(bookmark_bar_folders_names) == set(rule['names']) else 0.
    elif rule['type'] == "bookmark_bar_websites_urls":
        bookmark_bar_websites_urls = [bookmark['url'] for bookmark in bookmarks['bookmark_bar']['children'] if
                                      bookmark['type'] == 'url']
        return 1. if set(bookmark_bar_websites_urls) == set(rule['urls']) else 0.
    elif rule['type'] == "liked_authors_websites_urls":
        # Check if "liked authors" folder exists
        liked_authors_folder = next((bookmark for bookmark in bookmarks['bookmark_bar']['children'] if
                                     bookmark['type'] == 'folder' and bookmark['name'] == 'Liked Authors'), None)
        if liked_authors_folder:
            # Check if it contains the specified URLs
            liked_authors_urls = [bookmark['url'] for bookmark in liked_authors_folder['children'] if
                                  bookmark['type'] == 'url']

            urls = rule['urls']

            for idx, url in enumerate(urls):
                if isinstance(url, str):
                    urls[idx] = [url]

            combinations = product(*urls)

            for combination in combinations:
                if set(combination) == set(liked_authors_urls):
                    return 1.
            return 0.
        else:
            return 0.
    else:
        raise TypeError(f"{rule['type']} not support yet!")


def is_expected_search_query(active_tab_info: Dict[str, str], rules: Dict[str, Any]) -> float:
    expected = rules['expect']
    pattern = expected['pattern']
    matched = re.search(pattern, active_tab_info['url'])
    if matched:
        return 1.
    return 0.


def compare_pdfs(pdf1_path: Union[str, List[str]], pdf2_path: Union[str, List[str]]):
    """
    Compare two PDF files.
    """
    if type(pdf2_path) != list:
        pdf1_path, pdf2_path = [pdf1_path], [pdf2_path]

    def extract_text_from_pdf(pdf_path):
        """Extract text from each page of the PDF."""
        text = ""
        with fitz.open(pdf_path) as pdf:
            for page in pdf:
                text += page.get_text()
        return text.strip()

    score = 0.
    for path1, path2 in zip(pdf1_path, pdf2_path):
        try:
            text1 = extract_text_from_pdf(path1)
            text2 = extract_text_from_pdf(path2)
            score += fuzz.ratio(text1, text2) / 100
        except Exception as e:
            logger.info(f"[ERROR]: unexpected error occurred when comparing PDF files: {e}")
    return score / len(pdf2_path)


import fitz
from PIL import Image
from borb.pdf import Document
from borb.pdf import PDF

from pathlib import Path
import typing


def compare_pdf_images(pdf1_path: str, pdf2_path: str, **kwargs) -> float:
    if not pdf1_path or not pdf2_path:
        return 0.

    def extract_images_from_pdf(pdf_path):
        pdf_document = fitz.open(pdf_path)
        images = []

        for page_number in range(pdf_document.page_count):
            page = pdf_document[page_number]
            pixmap = page.get_pixmap()

            img = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)

            images.append(img)

        return images

    def fix_pdf(in_path: Path, out_path: Path) -> None:
        doc: typing.Optional[Document] = None
        with open(in_path, "rb") as fh:
            doc = PDF.loads(fh)
        with open(out_path, "wb") as fh:
            PDF.dumps(fh, doc)

    fix_pdf(Path(pdf1_path), Path(pdf1_path))
    fix_pdf(Path(pdf2_path), Path(pdf2_path))

    images1 = extract_images_from_pdf(pdf1_path)
    images2 = extract_images_from_pdf(pdf2_path)

    if len(images1) != len(images2):
        return 0.

    for img1, img2 in zip(images1, images2):
        if img1.tobytes() != img2.tobytes():
            return 0.

    return 1.


def compare_archive(pred_path: str, gold_path: str, **kwargs) -> float:
    """
    Compare two archives. Note that the files in the archives should be of the same type.
    """
    file_path = kwargs.pop('file_path', '')

    if not pred_path:
        return 0.
    pred_folder = os.path.splitext(pred_path)[0] + '_pred'
    gold_folder = os.path.splitext(gold_path)[0] + '_gold'

    if os.path.exists(pred_folder):  # remove existing folder for new predictions
        shutil.rmtree(pred_folder, ignore_errors=True)
    os.makedirs(pred_folder)
    shutil.unpack_archive(pred_path, pred_folder)

    if not os.path.exists(gold_folder):  # use cache if exists
        os.makedirs(gold_folder)
        shutil.unpack_archive(gold_path, gold_folder)

    pred_files = sorted(os.listdir(os.path.join(pred_folder, file_path)))
    gold_files = sorted(os.listdir(os.path.join(gold_folder, file_path)))

    if pred_files != gold_files:
        return 0.

    def get_compare_function():
        file_type = kwargs.pop('file_type', 'text')
        if file_type == 'text':
            from .vscode import compare_text_file
            return compare_text_file
        elif file_type == 'pdf':
            return compare_pdfs
        elif file_type == 'docx':
            from .docs import compare_docx_files
            return compare_docx_files
        elif file_type == 'ppt':
            from .slides import compare_pptx_files
            return compare_pptx_files
        elif file_type == 'image':
            from .vlc import compare_images
            return compare_images
        elif file_type == 'csv':
            from .table import compare_csv
            return compare_csv
        elif file_type == 'table':
            from .table import compare_table
            return compare_table
        elif file_type == 'audio':
            from .vlc import compare_audios
            return compare_audios
        elif file_type == 'video':
            from .vlc import compare_videos
            return compare_videos
        else:
            raise ValueError('[ERROR]: not support file type: %s' % file_type)

    score = 0
    compare_function = get_compare_function()
    for f1, f2 in zip(pred_files, gold_files):
        fp1 = os.path.join(pred_folder, file_path, f1)
        fp2 = os.path.join(gold_folder, file_path, f2)
        score += compare_function(fp1, fp2, **kwargs)
    return score / len(pred_files)


def compare_htmls(html_path1: str, html_path2: str) -> float:
    """
    Compare two HTML files.
    """
    with open(html_path1, 'r', encoding='utf-8') as inf:
        soup1 = BeautifulSoup(inf, 'lxml')
    with open(html_path2, 'r', encoding='utf-8') as inf:
        soup2 = BeautifulSoup(inf, 'lxml')

    def compare_elements(elem1, elem2):
        if not (isinstance(elem1, Tag) and isinstance(elem2, Tag)):
            return elem1 == elem2
        if elem1.name != elem2.name:
            return False
        if elem1.text.strip() != elem2.text.strip():
            return False
        if elem1.attrs != elem2.attrs:
            return False
        return True

    for elem1, elem2 in zip(soup1.recursiveChildGenerator(), soup2.recursiveChildGenerator()):
        if not compare_elements(elem1, elem2):
            return .0
    return 1.


def is_cookie_deleted(cookie_data, rule):
    """
    Check if the cookie is deleted.
    """

    if rule['type'] == 'domains':
        cookies_domains = [cookie[1] for cookie in cookie_data]
        for domain in rule['domains']:
            for cookies_domain in cookies_domains:
                if compare_urls(domain, cookies_domain):
                    return 0.
        return 1.
    else:
        raise TypeError(f"{rule['type']} not support yet!")


def is_shortcut_on_desktop(shortcuts: Dict[str, str], rule):
    """
    Check if the shortcut is on the desktop.
    """
    # fixme: if the name of the website changed in the future, this will not work; can be replaced with url
    if rule['type'] == 'name':
        for shortcut_path, shortcut_content in shortcuts.items():
            if "Name=" + rule['name'] + "\n" in shortcut_content:
                return 1.
        return 0.
    elif rule['type'] == 'url':
        raise TypeError(f"{rule['type']} not support yet!")
    elif rule['type'] == 'id':
        raise TypeError(f"{rule['type']} not support yet!")
    else:
        raise TypeError(f"{rule['type']} not support yet!")


def check_history_deleted(history_data, rule):
    """
    Check if the history is deleted.
    """

    if rule['type'] == 'keywords':
        history_domains = [history[0] for history in history_data]
        for keyword in rule['keywords']:
            for history_domain in history_domains:
                if keyword in history_domain:
                    return 0.
        return 1.
    else:
        raise TypeError(f"{rule['type']} not support yet!")


def check_enabled_experiments(enabled_experiments, rule):
    """
    Check if the enabled experiments are as expected.
    """
    enabled_experiments_names = [experiment.split("@")[0] for experiment in enabled_experiments]

    if rule['type'] == 'names':
        return 1. if enabled_experiments_names == rule['names'] else 0.
    else:
        raise TypeError(f"{rule['type']} not support yet!")


def check_font_size(font_size, rule):
    """
    Check if the font size is as expected.
    """

    default_font_size = font_size['default_font_size']
    if rule['type'] == 'value':
        return 1. if default_font_size == rule['value'] else 0.
    elif rule['type'] == 'range':
        return 1. if rule['min'] < default_font_size < rule['max'] else 0.
    else:
        raise TypeError(f"{rule['type']} not support yet!")


def is_added_to_steam_cart(active_tab_info, rule):
    """
    Check if the item is added to the Steam cart.
    """
    items = rule['items']

    content = active_tab_info['content']

    for item in items:
        if item not in content:
            return 0.

    return 1.
