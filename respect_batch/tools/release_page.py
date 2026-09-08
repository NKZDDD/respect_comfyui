"""从共用界面生成仅包含用户功能的发行页面，随后由构建器加密封装。"""
from html.parser import HTMLParser
import re


class UserPage(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        excluded = "data-admin" in attrs or attrs.get("id") == "tab-set"
        if self.skip or excluded:
            if tag not in self.VOID:
                self.skip += 1
            return
        if tag == "body":
            self.output.append('<body class="distribution"><input type="hidden" id="prov" value="preset">')
        else:
            self.output.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= 1
        else:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.output.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")

    def handle_decl(self, decl):
        self.output.append(f"<!{decl}>")


def render(source: str) -> bytes:
    source = re.sub(r"/\* @admin-start \*/.*?/\* @admin-end \*/", "", source, flags=re.S)
    source = source.replace("let RELEASE=false, PREVIEW=false;", "let RELEASE=true, PREVIEW=false;")
    source = re.sub(r'(<h2 id="modelHeading">).*?</h2>',
                    r'\1<i>1</i>选择模型<small>选择模型，添加任务即可生成</small></h2>', source)
    page = UserPage()
    page.feed(source)
    page.close()
    if page.skip:
        raise ValueError("发行界面标签未闭合")
    return "".join(page.output).encode("utf-8")
