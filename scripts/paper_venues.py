"""Curated importance tiers, then CV preference; stable slugs are URL/storage boundaries."""

YEARS = (2025, 2026, 2027)
VENUES = {
    # Leading venues follow the user-selected reading priority.
    "cvpr": ("CVPR", "conference", "IEEE/CVF Conference on Computer Vision and Pattern Recognition", "https://cvpr.thecvf.com/"),
    "neurips": ("NeurIPS", "conference", "Conference on Neural Information Processing Systems", "https://neurips.cc/"),
    "icml": ("ICML", "conference", "International Conference on Machine Learning", "https://icml.cc/"),
    "iclr": ("ICLR", "conference", "International Conference on Learning Representations", "https://iclr.cc/"),
    "tpami": ("TPAMI", "journal", "IEEE Transactions on Pattern Analysis and Machine Intelligence", "https://www.computer.org/csdl/journal/tp"),
    "siggraph": ("SIGGRAPH", "conference", "ACM SIGGRAPH Conference on Computer Graphics and Interactive Techniques", "https://www.siggraph.org/"),
    "iccv": ("ICCV", "conference", "IEEE/CVF International Conference on Computer Vision", "https://iccv.thecvf.com/"),
    "eccv": ("ECCV", "conference", "European Conference on Computer Vision", "https://www.ecva.net/papers.php"),
    "aaai": ("AAAI", "conference", "AAAI Conference on Artificial Intelligence", "https://ojs.aaai.org/index.php/AAAI"),
    "ijcv": ("IJCV", "journal", "International Journal of Computer Vision", "https://link.springer.com/journal/11263"),
    # Other core international venues and journals; CV first within the same importance tier.
    "tip": ("TIP", "journal", "IEEE Transactions on Image Processing", "https://signalprocessingsociety.org/publications-resources/ieee-transactions-image-processing"),
    "ijcai": ("IJCAI", "conference", "International Joint Conference on Artificial Intelligence", "https://www.ijcai.org/proceedings/"),
    "acmmm": ("ACM MM", "conference", "ACM International Conference on Multimedia", "https://www.acmmm.org/"),
    "tmm": ("TMM", "journal", "IEEE Transactions on Multimedia", "https://signalprocessingsociety.org/publications-resources/ieee-transactions-multimedia"),
    # Established specialist venues and journals; CV first within the same importance tier.
    "tcsvt": ("TCSVT", "journal", "IEEE Transactions on Circuits and Systems for Video Technology", "https://ieee-cas.org/publication/tcsvt"),
    "pr": ("Pattern Recognition", "journal", "Pattern Recognition", "https://www.sciencedirect.com/journal/pattern-recognition"),
    "wacv": ("WACV", "conference", "IEEE/CVF Winter Conference on Applications of Computer Vision", "https://wacv.thecvf.com/"),
    "bmvc": ("BMVC", "conference", "British Machine Vision Conference", "https://www.bmva.org/bmvc"),
    "accv": ("ACCV", "conference", "Asian Conference on Computer Vision", "https://accv2026.org/"),
    "tci": ("TCI", "journal", "IEEE Transactions on Computational Imaging", "https://signalprocessingsociety.org/publications-resources/ieee-transactions-computational-imaging"),
    "icassp": ("ICASSP", "conference", "IEEE International Conference on Acoustics, Speech and Signal Processing", "https://www.ieeeicassp.org/"),
    "icip": ("ICIP", "conference", "IEEE International Conference on Image Processing", "https://www.ieeeicip.org/"),
    # Specialist workshops; CV first within the same importance tier.
    "ntire": ("NTIRE", "workshop", "New Trends in Image Restoration and Enhancement", "https://www.cvlai.net/ntire/2026/"),
    "aim": ("AIM", "workshop", "Advances in Image Manipulation", "https://www.cvlai.net/aim/2025/"),
}
ISSNS = {"tpami": "0162-8828", "ijcv": "0920-5691", "tip": "1057-7149", "tcsvt": "1051-8215",
         "tmm": "1520-9210", "tci": "2333-9403", "pr": "0031-3203", "aaai": "2374-3468"}


def valid_dataset(venue, year):
    return venue in VENUES and str(year) in {str(y) for y in YEARS}


def not_held(venue, year):
    return (venue == "iccv" and year % 2 == 0) or (venue in {"eccv", "accv"} and year % 2 == 1)
