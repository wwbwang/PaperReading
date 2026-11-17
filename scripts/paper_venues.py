"""The explicitly requested reading list; stable slugs are URL/storage boundaries."""

YEARS = (2025, 2026, 2027)
VENUES = {
    "iclr": ("ICLR", "conference", "International Conference on Learning Representations", "https://iclr.cc/"),
    "cvpr": ("CVPR", "conference", "IEEE/CVF Conference on Computer Vision and Pattern Recognition", "https://cvpr.thecvf.com/"),
    "iccv": ("ICCV", "conference", "IEEE/CVF International Conference on Computer Vision", "https://iccv.thecvf.com/"),
    "eccv": ("ECCV", "conference", "European Conference on Computer Vision", "https://www.ecva.net/papers.php"),
    "neurips": ("NeurIPS", "conference", "Conference on Neural Information Processing Systems", "https://neurips.cc/"),
    "icml": ("ICML", "conference", "International Conference on Machine Learning", "https://icml.cc/"),
    "aaai": ("AAAI", "conference", "AAAI Conference on Artificial Intelligence", "https://ojs.aaai.org/index.php/AAAI"),
    "ijcai": ("IJCAI", "conference", "International Joint Conference on Artificial Intelligence", "https://www.ijcai.org/proceedings/"),
    "wacv": ("WACV", "conference", "IEEE/CVF Winter Conference on Applications of Computer Vision", "https://wacv.thecvf.com/"),
    "bmvc": ("BMVC", "conference", "British Machine Vision Conference", "https://www.bmva.org/bmvc"),
    "accv": ("ACCV", "conference", "Asian Conference on Computer Vision", "https://accv2026.org/"),
    "acmmm": ("ACM MM", "conference", "ACM International Conference on Multimedia", "https://www.acmmm.org/"),
    "icip": ("ICIP", "conference", "IEEE International Conference on Image Processing", "https://www.ieeeicip.org/"),
    "icassp": ("ICASSP", "conference", "IEEE International Conference on Acoustics, Speech and Signal Processing", "https://www.ieeeicassp.org/"),
    "tpami": ("TPAMI", "journal", "IEEE Transactions on Pattern Analysis and Machine Intelligence", "https://www.computer.org/csdl/journal/tp"),
    "ijcv": ("IJCV", "journal", "International Journal of Computer Vision", "https://link.springer.com/journal/11263"),
    "tip": ("TIP", "journal", "IEEE Transactions on Image Processing", "https://signalprocessingsociety.org/publications-resources/ieee-transactions-image-processing"),
    "tcsvt": ("TCSVT", "journal", "IEEE Transactions on Circuits and Systems for Video Technology", "https://ieee-cas.org/publication/tcsvt"),
    "tmm": ("TMM", "journal", "IEEE Transactions on Multimedia", "https://signalprocessingsociety.org/publications-resources/ieee-transactions-multimedia"),
    "tci": ("TCI", "journal", "IEEE Transactions on Computational Imaging", "https://signalprocessingsociety.org/publications-resources/ieee-transactions-computational-imaging"),
    "pr": ("Pattern Recognition", "journal", "Pattern Recognition", "https://www.sciencedirect.com/journal/pattern-recognition"),
    "ntire": ("NTIRE", "workshop", "New Trends in Image Restoration and Enhancement", "https://www.cvlai.net/ntire/2026/"),
    "aim": ("AIM", "workshop", "Advances in Image Manipulation", "https://www.cvlai.net/aim/2025/"),
}
ISSNS = {"tpami": "0162-8828", "ijcv": "0920-5691", "tip": "1057-7149", "tcsvt": "1051-8215",
         "tmm": "1520-9210", "tci": "2333-9403", "pr": "0031-3203", "aaai": "2374-3468"}


def valid_dataset(venue, year):
    return venue in VENUES and str(year) in {str(y) for y in YEARS}


def not_held(venue, year):
    return (venue == "iccv" and year % 2 == 0) or (venue in {"eccv", "accv"} and year % 2 == 1)
