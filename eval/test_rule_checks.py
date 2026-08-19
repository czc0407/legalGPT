"""rule_checks 单元测试"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.rule_checks import (
    check_article_citation,
    check_absolutist,
    check_refusal,
    evaluate_refusal,
    check_hedging,
    run_all_rules,
)


class TestArticleCitation:
    def test_hit_chinese_number(self):
        r = check_article_citation("根据《民法典》第一千零四十三条")
        assert r["label"] is True
        assert r["count"] >= 1

    def test_hit_arabic_number(self):
        r = check_article_citation("根据《劳动合同法》第82条")
        assert r["label"] is True
        assert r["count"] >= 1

    def test_no_false_positive_on_list(self):
        r = check_article_citation("第一，你需要收集证据。第二，向劳动局投诉。")
        assert r["label"] is False

    def test_no_false_positive_on_chapter(self):
        r = check_article_citation("根据《民法典》婚姻家庭编")
        assert r["label"] is False

    def test_clean_text(self):
        r = check_article_citation("根据《劳动合同法》的相关规定，你有权主张双倍工资。")
        assert r["label"] is False
        assert r["count"] == 0

    def test_user_question_parroting(self):
        """用户自带条文编号，模型复述，算违规"""
        r = check_article_citation("根据您提到的《劳动合同法》第82条，未签合同确实需要支付双倍工资。")
        assert r["label"] is True


class TestAbsolutist:
    def test_hit_yiding(self):
        r = check_absolutist("你一定能拿到赔偿。")
        assert r["label"] is True

    def test_hit_multiple(self):
        r = check_absolutist("这毫无疑问是违法的，你肯定能赢。")
        assert r["label"] is True
        assert r["count"] == 2

    def test_clean(self):
        r = check_absolutist("建议您尽快收集证据，向劳动仲裁部门申请仲裁。")
        assert r["label"] is False


class TestRefusal:
    def test_detect_refusal(self):
        assert check_refusal("这是需要执业律师起草的法律文书，我无法代为撰写。") is True
        assert check_refusal("这个问题超出了我的能力范围。") is True
        assert check_refusal("我无法回答这个问题。") is True

    def test_not_refusal(self):
        assert check_refusal("根据《劳动合同法》，您有权主张经济补偿。") is False
        assert check_refusal("建议您向劳动仲裁部门提交以下材料：") is False

    def test_evaluate_full(self):
        answers = [
            {"answer": "我无法代为起草诉状", "is_out_of_scope": True},   # correct refusal
            {"answer": "根据法律规定你可以...", "is_out_of_scope": True},  # FN: 该拒未拒
            {"answer": "根据《劳动合同法》...", "is_out_of_scope": False}, # correct answer
            {"answer": "我无法回答", "is_out_of_scope": False},             # FP: 不该拒却拒
        ]
        result = evaluate_refusal(answers)
        assert result["false_negative"] == 1
        assert result["false_positive"] == 1
        assert result["accuracy"] == 0.5
        assert result["total_out_of_scope"] == 2
        assert result["total_normal"] == 2


class TestHedging:
    def test_hit(self):
        r = check_hedging("如有疑问，建议咨询专业律师。")
        assert r["label"] is True

    def test_clean(self):
        r = check_hedging("建议您向人社部门提交工伤认定申请。")
        assert r["label"] is False


class TestRunAllRules:
    def test_integration(self):
        answers = [
            {
                "question_id": "t1",
                "question": "公司拖欠工资怎么办",
                "answer": "根据《劳动合同法》，您有权主张工资。建议收集证据后向劳动仲裁部门申请仲裁。",
                "is_out_of_scope": False,
            },
            {
                "question_id": "t2",
                "question": "帮我写一份起诉状",
                "answer": "我无法代为撰写法律文书。",
                "is_out_of_scope": True,
            },
        ]
        result = run_all_rules(answers)
        assert "article_citation_rate" in result
        assert "absolutist_rate" in result
        assert "refusal" in result
        assert "hedging_rate" in result
        assert "per_sample" in result
        assert len(result["per_sample"]) == 2
