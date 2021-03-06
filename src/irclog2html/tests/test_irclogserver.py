# -*- coding: utf-8 -*-
import gzip
import os
import shutil
import tempfile
import doctest
import unittest
from contextlib import closing

import mock

from irclog2html.irclogserver import parse_path, application


here = os.path.dirname(__file__)


def gzip_copy(src, dst):
    with open(src, 'rb') as fi:
        with closing(gzip.open(dst, 'wb')) as fo:
            shutil.copyfileobj(fi, fo)


def set_up_sample():
    tmpdir = tempfile.mkdtemp(prefix='irclog2html-test-')
    gzip_copy(os.path.join(here, 'sample.log'),
              os.path.join(tmpdir, 'sample-2013-03-17.log.gz'))
    shutil.copy(os.path.join(here, 'sample.log'),
                os.path.join(tmpdir, 'sample-2013-03-18.log'))
    with open(os.path.join(tmpdir, "index.html"), "w") as f:
        f.write("This is the index")
    with open(os.path.join(tmpdir, "font.css"), "w") as f:
        f.write("* { font: comic sans; }")
    os.mkdir(os.path.join(tmpdir, "#chan"))
    with open(os.path.join(tmpdir, "#chan", "index.html"), "w") as f:
        f.write("#chan index")
    return tmpdir


def clean_up_sample(tmpdir):
    shutil.rmtree(tmpdir)


def doctest_parse_path():
    """Test for parse_path.

    This function decides whether to search or to display a file based
    on URL path:

        >>> parse_path(dict(PATH_INFO='/search'))
        (None, 'search')

        >>> parse_path(dict(PATH_INFO='/#channel-2015-05-05.log.html'))
        (None, '#channel-2015-05-05.log.html')

    When there is no file name, we show the index:

        >>> parse_path(dict(PATH_INFO='/'))
        (None, 'index.html')

    Any slashes other than the leading one result in None:

        >>> parse_path(dict(PATH_INFO='/../../etc/passwd'))
        (None, None)

    But there is an option to serve a directory with subdir for each
    channel.  If IRCLOG_CHAN_DIR is defined, the first traversal step
    is the first element of the returned tuple:

        >>> parse_path(dict(PATH_INFO='/#random/search',
        ...            IRCLOG_CHAN_DIR='/opt/irclog'))
        ('#random', 'search')


        >>> parse_path(dict(PATH_INFO='/#random/',
        ...            IRCLOG_CHAN_DIR='/opt/irclog'))
        ('#random', 'index.html')

    If the path does not contain the channel name, tough cookies:

        >>> parse_path(dict(PATH_INFO='/index.html',
        ...            IRCLOG_CHAN_DIR='/opt/irclog'))
        (None, 'index.html')

    Hacking verboten:

        >>> parse_path(dict(PATH_INFO='/../index.html',
        ...            IRCLOG_CHAN_DIR='/opt/irclog'))
        (None, None)

        >>> parse_path(dict(PATH_INFO='/#random/../index.html',
        ...            IRCLOG_CHAN_DIR='/opt/irclog'))
        ('#random', None)

    """


class Response(object):
    pass


class TestApplication(unittest.TestCase):

    def setUp(self):
        self.tmpdir = set_up_sample()

    def tearDown(self):
        clean_up_sample(self.tmpdir)

    if not hasattr(unittest.TestCase, 'assertIn'):
        def assertIn(self, needle, haystack):
            self.assertTrue(needle in haystack, haystack)

    def request(self, path='/', expect=200, extra_env=None):
        environ = {
            'IRCLOG_LOCATION': self.tmpdir,
            'PATH_INFO': path.partition('?')[0],
            'QUERY_STRING': path.partition('?')[-1],
            'wsgi.input': None,
        }
        if extra_env:
            environ.update(extra_env)
        start_response = mock.Mock()
        response = Response()
        response.body = b''.join(application(environ, start_response))
        self.assertEqual(start_response.call_count, 1)
        status, headers = start_response.call_args[0]
        response.status_string = status
        response.status = int(status.split()[0])
        response.header_list = headers
        response.headers = dict(headers)
        response.content_type = response.headers['Content-Type']
        response.location = response.headers.get('Location')
        self.assertEqual(response.status, expect)
        return response

    def test_root(self):
        response = self.request('/')
        self.assertEqual(response.body, b'This is the index')
        self.assertEqual(response.content_type, 'text/html; charset=UTF-8')

    def test_root_without_index_html(self):
        os.unlink(os.path.join(self.tmpdir, 'index.html'))
        response = self.request('/', expect=302)
        self.assertEqual(response.body, b'Try /search')
        self.assertEqual(response.content_type, 'text/plain')
        self.assertEqual(response.location, '/search')

    def test_search_page(self):
        response = self.request('/search')
        self.assertEqual(response.content_type, 'text/html; charset=UTF-8')
        self.assertIn(b'<title>Search IRC logs</title>', response.body)

    def test_search(self):
        response = self.request('/search?q=bot')
        self.assertEqual(response.content_type, 'text/html; charset=UTF-8')
        self.assertIn(b'<title>Search IRC logs</title>', response.body)
        self.assertIn(b'<p>10 matches in 2 log files with 20 lines',
                      response.body)

    def test_log_file(self):
        response = self.request('/sample-2013-03-18.log')
        self.assertEqual(response.content_type, 'text/plain; charset=UTF-8')
        self.assertIn(b'2005-01-08T23:33:54  *** povbot has joined #pov',
                      response.body)
        self.assertIn(u'ąčę'.encode('UTF-8'), response.body)
        self.assertIn(u'<mgedmin> š'.encode('UTF-8'), response.body)

    def test_builtin_css(self):
        response = self.request('/irclog.css')
        self.assertEqual(response.content_type, 'text/css')
        self.assertIn(b'div.searchbox {', response.body)

    @mock.patch('irclog2html.irclogserver.CSS_FILE', '/nosuchfile')
    def test_builtin_css_missing(self):
        response = self.request('/irclog.css', expect=404)
        self.assertEqual(response.content_type, 'text/plain')
        self.assertIn(b'Not found', response.body)

    def test_other_css(self):
        response = self.request('/font.css')
        self.assertEqual(response.content_type, 'text/css')
        self.assertIn(b'{ font: comic sans; }', response.body)

    def test_not_found(self):
        response = self.request('/nosuchfile', expect=404)
        self.assertEqual(response.content_type, 'text/plain')
        self.assertIn(b'Not found', response.body)

    def test_path_with_slashes(self):
        response = self.request('/./index.html', expect=404)
        self.assertEqual(response.content_type, 'text/plain')
        self.assertIn(b'Not found', response.body)

    def test_path_with_backslashes(self):
        response = self.request('/.\\index.html', expect=404)
        self.assertEqual(response.content_type, 'text/plain')
        self.assertIn(b'Not found', response.body)

    def test_chan_index(self):
        response = self.request(
            '/#chan/',
            extra_env={"IRCLOG_CHAN_DIR": self.tmpdir})
        self.assertEqual(response.content_type, 'text/html; charset=UTF-8')
        self.assertEqual(b'#chan index', response.body)

    def test_chan_search_page(self):
        response = self.request(
            '/#chan/search',
            extra_env={"IRCLOG_CHAN_DIR": self.tmpdir})
        self.assertEqual(response.content_type, 'text/html; charset=UTF-8')
        self.assertIn(b'<title>Search IRC logs</title>', response.body)

    def test_chan_listing(self):
        response = self.request(
            '/',
            extra_env={"IRCLOG_CHAN_DIR": self.tmpdir})
        self.assertEqual(response.content_type, 'text/html; charset=UTF-8')
        self.assertIn(b'IRC logs', response.body)
        self.assertIn(b'<a href="%23chan/">#chan</a>', response.body)

    def test_chan_error(self):
        response = self.request(
            '/../index.html',
            extra_env={"IRCLOG_CHAN_DIR": self.tmpdir},
            expect=404)
        self.assertEqual(response.content_type, 'text/plain')
        self.assertIn(b'Not found', response.body)

    @mock.patch("os.environ")
    def test_chan_os_environ(self, environ):
        os.environ.get = {"IRCLOG_CHAN_DIR": self.tmpdir}.get
        response = self.request('/')
        self.assertEqual(response.content_type, 'text/html; charset=UTF-8')
        self.assertIn(b'IRC logs', response.body)
        self.assertIn(b'<a href="%23chan/">#chan</a>', response.body)

    @mock.patch("os.environ")
    def test_chan_search_page(self, environ):
        os.environ.get = {"IRCLOG_CHAN_DIR": self.tmpdir}.get
        response = self.request(
            '/#chan/search')
        self.assertEqual(response.content_type, 'text/html; charset=UTF-8')
        self.assertIn(b'<title>Search IRC logs</title>', response.body)


def test_suite():
    return unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromName(__name__),
        doctest.DocTestSuite()
    ])
