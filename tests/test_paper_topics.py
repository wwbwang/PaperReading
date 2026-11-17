"""Topic document frequency, normalization and exact intersection semantics."""
import unittest

from scripts.paper_topics import TopicIndex, topic_key


class TopicTests(unittest.TestCase):
    def setUp(self):
        self.index = TopicIndex([
            ("a", "Video Super-Resolution;video super resolution;Image Restoration;C++"),
            ("b", "VIDEO SUPER RESOLUTION;C#"),
            ("c", "Video Restoration;Diffusion"),
            ("d", ""),
        ])

    def test_counts_papers_not_keyword_repetitions_and_preserves_phrases(self):
        result = self.index.summarize(["a", "b", "a", "d"])
        words = {word["key"]: word for word in result["words"]}
        self.assertEqual((result["paper_count"], result["keyword_papers"], result["missing_keywords"]), (3, 2, 1))
        self.assertEqual(words["video super resolution"]["count"], 2)
        self.assertAlmostEqual(words["video super resolution"]["percentage"], 200 / 3)
        self.assertNotIn("video", words)

    def test_topics_do_not_invent_synonyms_or_merge_programming_languages(self):
        self.assertEqual(topic_key("Ｖｉｄｅｏ Super—Resolution"), "video super resolution")
        self.assertNotEqual(topic_key("C++"), topic_key("C#"))
        self.assertFalse(self.index.matches("c", {"video super resolution"}))
        self.assertTrue(self.index.matches("a", {"video super resolution", "image restoration"}))
        self.assertFalse(self.index.matches("b", {"video super resolution", "image restoration"}))

    def test_empty_and_missing_keywords_are_distinct_from_unknown_papers(self):
        self.assertEqual(self.index.summarize([])["words"], [])
        self.assertEqual(self.index.summarize(["d"])["missing_keywords"], 1)
        with self.assertRaises(ValueError):
            self.index.summarize(["unknown"])

    def test_order_is_deterministic_and_top_words_keep_their_true_counts(self):
        self.assertEqual(self.index.summarize(["a", "b", "c"]), self.index.summarize(["c", "a", "b"]))
        result = self.index.summarize(["a", "b", "c"], limit=1)
        self.assertEqual(len(result["words"]), 1)
        self.assertGreater(result["topic_count"], 1)
        self.assertEqual(result["words"][0]["count"], 2)


if __name__ == "__main__":
    unittest.main()
