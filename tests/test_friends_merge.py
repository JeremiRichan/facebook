from fb_modular.extractors.friends import merge_candidates

FORBIDDEN = set()


def run(raw, exclude=()):
    found = {}
    added = merge_candidates(raw, found, FORBIDDEN, set(exclude), 2600)
    return added, found


def test_notifications_from_the_real_log_are_ignored():
    raw = [
        ['https://web.facebook.com/notifications/', '', '', ''],
        ['https://web.facebook.com/stories/210789320829754/UzpfSVNDOjE2/?source=notification&notif_id=17', 'Unread Raïssa mentioned you', '', ''],
        ['https://web.facebook.com/permalink.php?story_fbid=pfbid04k&id=615&comment_id=2&notif_id=18&ref=notif', 'Raïssa Ainamalala mentioned you in a comment', '', ''],
        ['https://web.facebook.com/onthisday/?source=notification&notif_id=19', 'You have memories to look back on today.', '', ''],
        ['https://web.facebook.com/professional_dashboard/levels/?notif_id=20&ref=notif', 'Make progress this week.', '', ''],
    ]
    added, found = run(raw)
    assert added == 0 and found == {}


def test_friend_rows_like_the_screenshot():
    raw = [
        ['https://web.facebook.com/vero.hanitry', 'Vero Hanitry Ny Aina', '', 'https://scontent.x/a.jpg'],
        ['https://web.facebook.com/feno.soa.1', 'Feno Soa', '', 'https://scontent.x/b.jpg'],
        ['https://web.facebook.com/profile.php?id=100099', 'Dadan\'i Branham', '', 'https://scontent.x/c.jpg'],
    ]
    added, found = run(raw)
    assert added == 3
    assert set(found) == {'vero.hanitry', 'feno.soa.1', '100099'}
    assert found['100099']['profile_url'] == 'https://www.facebook.com/profile.php?id=100099'


def test_photo_link_without_text_then_name_link_are_merged():
    raw = [
        ['https://www.facebook.com/samia.rakoto', '', '', 'https://scontent.x/s.jpg'],
        ['https://www.facebook.com/samia.rakoto', 'Samia Rakoto', '', ''],
        ['https://www.facebook.com/samia.rakoto', '30 mutual friends', '', ''],
    ]
    added, found = run(raw)
    assert added == 1
    entry = found['samia.rakoto']
    assert entry['display_name'] == 'Samia Rakoto' and entry['photo_url'].endswith('s.jpg')


def test_aria_label_is_used_when_text_is_empty():
    added, found = run([['https://www.facebook.com/rami.x', '', 'Rami Andria', '']])
    assert added == 1 and found['rami.x']['display_name'] == 'Rami Andria'


def test_own_profile_is_excluded():
    added, found = run([['https://www.facebook.com/moi.meme', 'Moi Meme', '', '']],
                       exclude={'moi.meme'})
    assert added == 0 and not found


def test_duplicates_counted_once():
    row = ['https://www.facebook.com/a.b.c', 'Alpha Beta', '', '']
    added, found = run([row, row, row])
    assert added == 1 and len(found) == 1


def test_non_cdn_images_are_not_kept_as_photos():
    _, found = run([['https://www.facebook.com/a.b.c', 'Alpha Beta', '', 'data:image/gif;base64,xx']])
    assert found['a.b.c']['photo_url'] == ''
