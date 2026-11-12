from sellerscope.services.mailer import build_message


def test_subject_cannot_inject_headers() -> None:
    message = build_message("a@example.com", "Hi\r\nBcc: victim@example.com\nX", "body")
    assert message["Subject"] == "Hi Bcc: victim@example.com X"
    assert message["Bcc"] is None
    assert len(build_message("a@example.com", "x" * 500, "b")["Subject"]) == 200
