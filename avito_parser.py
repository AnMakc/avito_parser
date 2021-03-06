from urllib.parse import quote
from datetime import datetime
import re
import requests
import time
from bs4 import BeautifulSoup


# locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8') doesn't work in Docker container


class TooManyRequests(Exception):
    '''raises in fetch_page function if request redirected to https://www.avito.ru/blocked'''
    pass


def get_all_ads(query, sort_by=None, by_title=False, with_images=False, owner=None, pause=None):
    '''Yields dicts with ad info (title, link, price and date).

    Keyword arguments:
    query -- search query, like 'audi tt'
    sort_by -- method of sorting, 'date', 'price', 'price_desc' (price descending)
               default None (yields ads sorted by Avito algorithm)
    by_title -- if True yields only ads with query in title
                default False
    with_images -- if True yields only ads with query in title
                   default False
    owner -- if 'private' yields only private ads, if 'company' only company
             default None (yields all ads)
    pause -- optional pause between request to avoid instant ban (in seconds)
             default None (no pause)
    '''
    search_url = generate_search_url(query, sort_by, by_title, with_images, owner)
    for page in get_pages(search_url, pause):
        ads = get_ads_from_page(page)
        if not ads:
            break
        for ad in ads:
            yield agregate_ad_info(ad)


def generate_search_url(query, sort_by, by_title, with_images, owner):
    '''Generates url by search parametres

    raises ValueError if sort_by or owner argument is not correct
    '''
    sort_values = {'date' : '104', 'price' : '1', 'price_desc' : '2', None : '101'}
    owners = {'private': '1', 'company': '2', None: '0'}
    if sort_by not in sort_values:
        raise ValueError('Sorting by {} is not supported'.format(sort_by))
    if owner not in owners:
        raise ValueError('Owner can be only private or company')
    urlencoded_query = quote(query)
    return 'https://www.avito.ru/moskva?s={}&bt={}&q={}&i={}&user={}'.format(sort_values[sort_by],
                                                                             int(by_title),
                                                                             urlencoded_query,
                                                                             int(with_images),
                                                                             owners[owner])+'&p={}'


def agregate_ad_info(ad):
    return {
        'Title': get_title(ad),
        'Link': get_link(ad),
        'Price': get_price(ad),
        'Date': normalize_date(get_date(ad)),
    }


def get_title(ad):
    return ad.find('a', attrs={'itemprop': 'url'}).contents[0].strip()


def get_link(ad):
    base_url = 'https://www.avito.ru'
    return base_url + ad.find('a', attrs={'itemprop': 'url'})['href']


def get_price(ad):
    price_str = ad.find('span', attrs={'class': 'snippet-price'}).contents[0]
    price_str = re.sub('[^\d]', '', price_str)
    try:
        return int(price_str)
    except ValueError:
        return None


def get_date(ad):
    date_node = ad.find('div', attrs={'class': 'snippet-date-info'})
    if date_node.attrs['data-tooltip'].strip():
        date = date_node.attrs['data-tooltip']
    else:
        date = date_node.contents[0]

    return date.strip().replace('\xa0', ' ')


def normalize_date(date):
    '''Leads date to '%Y-%m-%d %H:%M' form (like 2019-01-10 09:41)
    if no time specified leads to '%Y-%m-%d' (2019-01-10)
    '''
    if 'Вчера' in date or 'Сегодня' in date:
        date = convert_relative_date_to_absolute(date)
        return str(datetime.strptime(date, '%d %m %Y %H:%M'))[:-3] # seconds removed
    date = replace_month_name_with_number(date)
    if ':' in date:
        return str(datetime.strptime(date, '%d %m %H:%M').replace(year=get_current_year()))[:-3]
    return str(datetime.strptime(date, '%d %m %Y').date())


def convert_relative_date_to_absolute(date):
    '''Converts date from 'Вчера 15:29' form to '10 1 2019 15:29' '''
    current_day = get_current_day()
    if 'Вчера' in date:
        return replace_relative_day_with_absolute(date, 'Вчера', current_day - 1)
    return replace_relative_day_with_absolute(date, 'Сегодня', current_day)


def replace_month_name_with_number(date):
    months = {'января': '1', 'февраля': '2', 'марта': '3', 'апреля': '4', 'мая': '5', 'июня': '6',
              'июля': '7', 'августа': '8', 'сентября': '9', 'октября': '10', 'ноября': '11',
              'декабря': '12'}
    date_splitted = date.split()
    date_splitted[1] = months[date_splitted[1]]
    return ' '.join(d for d in date_splitted)


def replace_relative_day_with_absolute(date, relative_day, absolute_day):
    return '{} {} {}'.format(absolute_day,
                             get_current_month(),
                             get_current_year()) + date.replace(relative_day, '')


def get_current_day():
    return datetime.today().day


def get_current_month():
    return '{:%m}'.format(datetime.now())


def get_current_year():
    return datetime.today().year


def get_pages(search_url, pause=None):
    '''Yields page html as string until it reaches page with nothing found error.
    Optional pause between requests can be set to avoid instant ban
    '''
    page_number = 1
    page = fetch_page(search_url.format(page_number))
    while is_page_exists(page):
        yield page
        page_number += 1
        if pause is not None:
            time.sleep(pause)
        page = fetch_page(search_url.format(page_number))


def get_ads_from_page(page):
    bs_page = get_beautiful_soup(page)
    remote_ads = bs_page.find('div', attrs={'class': 'extra-block__header'})
    if remote_ads is not None:
        return remote_ads.find_all_previous('div', attrs={'class': 'item_table-wrapper'})
    else:
        return bs_page.find_all('div', attrs={'class': 'item_table-wrapper'})


def fetch_page(page_url):
    '''Returns page html as string

    raises TooManyRequest if request redirected to https://www.avito.ru/blocked
    '''
    response = requests.get(page_url)
    if response.url == 'https://www.avito.ru/blocked':
        raise TooManyRequests('IP temporarily blocked')
    return response.text


def get_beautiful_soup(html):
    return BeautifulSoup(html, 'lxml')


def is_page_exists(page):
    return get_beautiful_soup(page).find('div', text=re.compile("Ничего не нашлось по запросу.*")) is None
