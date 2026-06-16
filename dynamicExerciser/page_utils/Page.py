class Page:
    # 页面的index(通过index来查找页面截图)
    index = None
    # 页面通过md5标示
    page_md5 = None
    # 页面字符串Dump(后续会用于页面相似度计算)
    page_dump_str = None
    # 页面可点击位置
    click_locations = None
    click_index = None

    def __init__(self, index, page_md5, page_dump_str):
        self.index = index
        self.page_md5 = page_md5
        self.page_dump_str = page_dump_str
        self.click_locations = []
        self.click_index = 0
        self.click_meta = {}

    def append_new_click_location(self, new_click_location):
        self.click_locations.append(new_click_location)

    def append_new_click_locations(self, new_click_locations):
        for new_click_location in new_click_locations:
            if new_click_location not in self.click_locations:
                self.append_new_click_location(new_click_location)



    def set_index(self, new_index):
        self.index = new_index



    @staticmethod
    def _k(x, y): return f"{int(x)},{int(y)}"

    def register_click_meta(self, x, y, text="", bbox=None, score=0.0, source="ocr"):
        self.click_meta[self._k(x, y)] = {
            "text": text or "",
            "bbox": bbox or [int(x), int(y), 0, 0],
            "score": float(score),
            "source": source
        }

    def get_click_meta(self, x, y):
        return self.click_meta.get(self._k(x, y))