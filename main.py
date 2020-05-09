import random
import re

import pymysql
import telegram

from config import *  # pylint: disable=E0401,W0401,W0614


db = pymysql.connect(
    host=DB_HOST,
    user=DB_USER,
    passwd=DB_PASS,
    db=DB_DB,
    charset='utf8mb4',
)
cur = db.cursor()


class STATUS:
    NEW = 'new'
    FILLING = 'filling'
    SUBMITTED = 'submitted'
    REJECTED = 'rejected'
    BANNED = 'banned'
    APPROVED = 'approved'
    JOINED = 'joined'


class PERMISSION:
    SUPER = 'super'
    GRANT = 'grant'
    REVIEW = 'review'


class Userinfo():
    full_name = None
    username = None
    status = STATUS.NEW
    admin_comment = None

    def __init__(self, user_id):
        self.user_id = user_id

        cur.execute("""SELECT `full_name`, `username`, `status`, `admin_comment`, `question`, `answer`
                    FROM `user` WHERE `user_id` = %s""",
                    (user_id))
        row = cur.fetchone()

        if row is None:
            self.exists = False
        else:
            self.exists = True
            self.full_name = row[0]
            self.username = row[1]
            self.status = row[2]
            self.admin_comment = row[3]
            self.question = row[4]
            self.answer = row[5]

    def format_user_id(self):
        return '<a href="tg://user?id={0}">{0}</a>'.format(
            self.user_id,
        )

    def format_full(self):
        if not self.exists:
            return self.format_user_id()

        return '{0} <a href="tg://user?id={0}">{1}</a> {2}'.format(
            self.user_id,
            self.full_name,
            ' (@{})'.format(self.username) if self.username else '',
        )

    def update_name(self, full_name, username):
        if not self.exists:
            cur.execute("""INSERT INTO `user` (`user_id`) VALUES (%s)""",
                        (user_id))
            db.commit()
            self.exists = True
        if full_name != self.full_name or username != self.username:
            cur.execute("""UPDATE `user` SET `full_name` = %s, `username` = %s WHERE `user_id` = %s""",
                        (full_name, username, self.user_id))
            db.commit()

            self.full_name = full_name
            self.username = username

    def update_status(self, status):
        cur.execute("""UPDATE `user` SET `status` = %s WHERE `user_id` = %s""",
                    (status, self.user_id))
        db.commit()

    def update_question(self, question):
        cur.execute("""UPDATE `user` SET `question` = %s WHERE `user_id` = %s""",
                    (question, self.user_id))
        db.commit()

    def update_answer(self, answer):
        cur.execute("""UPDATE `user` SET `answer` = %s WHERE `user_id` = %s""",
                    (answer, self.user_id))
        db.commit()

    def update_admin_comment(self, admin_comment):
        cur.execute("""UPDATE `user` SET `admin_comment` = %s WHERE `user_id` = %s""",
                    (admin_comment, self.user_id))
        db.commit()

    def get_permissions(self):
        permissions = []

        cur.execute("""SELECT `permission` FROM `permissions` WHERE `admin_user_id` = %s""",
                    (self.user_id))
        rows = cur.fetchall()
        for row in rows:
            permissions.append(row[0])

        return permissions

    def grant(self, permission):
        cur.execute("""INSERT INTO `permissions` (`admin_user_id`, `permission`) VALUES (%s, %s)""",
                    (self.user_id, permission))
        db.commit()

    def revoke(self, permission):
        cur.execute("""DELETE FROM `permissions` WHERE `admin_user_id` = %s AND `permission` = %s""",
                    (self.user_id, permission))
        db.commit()


class System:
    def __init__(self):
        self.bot = telegram.Bot(TG_TOKEN)

    def log(self, text):
        cur.execute("""INSERT INTO `log` (`text`) VALUES (%s)""",
                    (str(text)))
        db.commit()

    def main(self, data):
        update = telegram.Update.de_json(data, self.bot)

        chat_id = update.effective_chat.id

        if chat_id > 0:
            self.handle_user(update)
        elif chat_id == CENSORED_CHAT_ID:
            self.handle_censored(update)
        elif chat_id == ADMIN_CHAT_ID:
            self.handle_admin(update)

    def handle_user(self, update):
        text = update.message.text
        user_id = update.effective_user.id

        self.log('user {} {}'.format(user_id, text))

        userinfo = Userinfo(user_id)
        userinfo.update_name(update.effective_user.full_name, update.effective_user.username)

        if userinfo.status == STATUS.NEW:
            if text == '/start':
                update.message.reply_text(
                    '您從未進行過任何申請，使用 /request 開始新申請'
                )
            elif text == '/request':
                self.user_new_request(update, userinfo)

        elif userinfo.status == STATUS.FILLING:
            if text == '/request':
                message = '您的入群問題為：\n{}\n-----\n'.format(userinfo.question)
                if userinfo.answer:
                    message += '您目前答案為：\n{}\n-----\n'.format(userinfo.answer)
                message += '請使用 /answer 換行後接著您的答案，答案請註明題號'
                update.message.reply_text(message)
                return

            if re.search(r'^/answer\s*$', text):
                update.message.reply_text(
                    '請在該指令後附加您的答案，範例：\n-----\n/answer\n1. 答案一\n2. 答案二...'
                )
                return

            m = re.search(r'^/answer\s+([\s\S]+)$', text)
            if m:
                answer = m.group(1)
                userinfo.update_answer(answer)
                update.message.reply_text(
                    '已收到您的答案，使用 /request 確認您目前儲存的答案\n'
                    + '可再次使用 /answer 覆蓋您的答案\n'
                    + '或是使用 /submit 送出申請，送出申請後則無法再修改答案'
                )
                return

            if text == '/submit':
                userinfo.update_status(STATUS.SUBMITTED)
                userinfo.update_admin_comment(None)
                update.message.reply_text(
                    '您的入群申請已送出，請耐心等候'
                )

                self.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text='收到一則來自 {} 的申請'.format(userinfo.format_full()),
                    parse_mode=telegram.ParseMode.HTML,
                )
                return

            update.message.reply_text(
                '您正在回答入群問題，使用 /request 查看您的問題'
            )
            return

        elif userinfo.status == STATUS.SUBMITTED:
            update.message.reply_text(
                '您的入群申請已送出，請耐心等候'
            )
        elif userinfo.status == STATUS.REJECTED:
            if text == '/request':
                self.user_new_request(update, userinfo)
            else:
                message = '您的入群申請被拒絕\n'
                if userinfo.admin_comment:
                    message += '管理員有此留言：{}\n'.format(userinfo.admin_comment)
                message += '使用 /request 再次提出申請'

                update.message.reply_text(message)
        elif userinfo.status == STATUS.BANNED:
            update.message.reply_text(
                '您已被禁止提出新申請'
            )
        elif userinfo.status == STATUS.APPROVED:
            if text == '/join':
                link = self.bot.export_chat_invite_link(chat_id=CENSORED_CHAT_ID)
                message = (
                    '加群連結為\n'
                    + '{}\n'
                    + '請立即加入群組以免連結失效\n'
                    + '此連結僅限您可使用，分享給他人將導致您的入群許可被撤銷'
                ).format(link)

                update.message.reply_text(message)
            else:
                update.message.reply_text(
                    '您已通過申請，使用 /join 取得入群連結'
                )
        elif userinfo.status == STATUS.JOINED:
            update.message.reply_text(
                '您已加入群組'
            )

    def user_new_request(self, update, userinfo):
        user_questions = []
        for qid, questions in enumerate(QUESTIONS, 1):
            user_questions.append('{}. {}'.format(qid, random.choice(questions)))
        user_questions = '\n'.join(user_questions)

        userinfo.update_status(STATUS.FILLING)
        userinfo.update_question(user_questions)
        userinfo.update_answer(None)

        update.message.reply_text(
            '您的入群問題為：\n{}\n----\n請使用 /answer 換行後接著您的答案，答案請註明題號'.format(user_questions)
        )

    def handle_censored(self, update):
        if update.message.new_chat_members:
            user_id = update.effective_user.id

            userinfo = Userinfo(user_id)
            userinfo.update_name(update.effective_user.full_name, update.effective_user.username)

            if userinfo.status == STATUS.APPROVED:
                userinfo.update_status(STATUS.JOINED)
            elif userinfo.status == STATUS.JOINED:
                update.message.reply_text('已通過申請')
            else:
                update.effective_chat.kick_member(
                    user_id=user_id,
                    until_date=0,
                )

    def handle_admin(self, update):
        text = update.message.text
        admininfo = Userinfo(update.effective_user.id)

        self.log('admin {}'.format(text))

        m = re.search(r'^/review (\d+)$', text)
        if m:
            reviewed_user_id = int(m.group(1))
            userinfo = Userinfo(reviewed_user_id)

            if userinfo.status == STATUS.SUBMITTED:
                message = (
                    '{0} 的申請問題如下：\n'
                    + '{1}\n'
                    + '-----\n'
                    + '答案如下：\n'
                    + '{2}\n'
                    + '-----\n'
                ).format(
                    userinfo.format_full(),
                    userinfo.question,
                    userinfo.answer,
                )
                if PERMISSION.REVIEW in admininfo.get_permissions():
                    message += (
                        '使用 /comment 設定回應訊息\n'
                        + '/approve 接受申請，/reject 拒絕申請'
                    )
                else:
                    message += '您沒有權限審核申請'
                update.message.reply_text(message, parse_mode=telegram.ParseMode.HTML)
            else:
                update.message.reply_text(
                    '{} 目前沒有申請'.format(userinfo.format_user_id()),
                    parse_mode=telegram.ParseMode.HTML,
                )

        m = re.search(r'^/comment\s*(\d+)\s*([\s\S]+)$', text)
        if m:
            if PERMISSION.REVIEW not in admininfo.get_permissions():
                update.message.reply_text(
                    '您沒有足夠權限進行此操作',
                )
                return

            reviewed_user_id = int(m.group(1))
            comment = m.group(2)

            userinfo = Userinfo(reviewed_user_id)

            if userinfo.status == STATUS.SUBMITTED:
                userinfo.update_admin_comment(comment)
                update.message.reply_text('已設定回應訊息')
            else:
                update.message.reply_text(
                    '{} 目前沒有申請'.format(userinfo.format_full()),
                    parse_mode=telegram.ParseMode.HTML,
                )

        m = re.search(r'^/approve (\d+)$', text)
        if m:
            reviewed_user_id = int(m.group(1))
            userinfo = Userinfo(reviewed_user_id)

            if PERMISSION.REVIEW not in admininfo.get_permissions():
                update.message.reply_text(
                    '您沒有足夠權限進行此操作',
                )
                return

            if userinfo.status == STATUS.SUBMITTED:
                userinfo.update_status(STATUS.APPROVED)
                update.message.reply_text(
                    '已批准 {} 的申請'.format(userinfo.format_full()),
                    parse_mode=telegram.ParseMode.HTML,
                )

                message = '您的入群申請已通過'
                if userinfo.admin_comment:
                    message += '\n管理員有此留言：{}\n'.format(userinfo.admin_comment)
                message += '使用 /join 取得加群連結'

                self.bot.send_message(
                    chat_id=reviewed_user_id,
                    text=message,
                )
            else:
                update.message.reply_text(
                    '{} 目前沒有申請'.format(userinfo.format_full()),
                    parse_mode=telegram.ParseMode.HTML,
                )

        m = re.search(r'^/reject (\d+)$', text)
        if m:
            reviewed_user_id = int(m.group(1))
            userinfo = Userinfo(reviewed_user_id)

            if PERMISSION.REVIEW not in admininfo.get_permissions():
                update.message.reply_text(
                    '您沒有足夠權限進行此操作',
                )
                return

            if userinfo.status == STATUS.SUBMITTED:
                userinfo.update_status(STATUS.REJECTED)
                update.message.reply_text(
                    '已拒絕 {} 的申請'.format(userinfo.format_full()),
                    parse_mode=telegram.ParseMode.HTML,
                )

                message = '您的入群申請被拒絕\n'
                if userinfo.admin_comment:
                    message += '管理員有此留言：{}\n'.format(userinfo.admin_comment)
                message += '使用 /request 再次提出申請'

                self.bot.send_message(
                    chat_id=reviewed_user_id,
                    text=message,
                )
            else:
                update.message.reply_text(
                    '{} 目前沒有申請'.format(userinfo.format_full()),
                    parse_mode=telegram.ParseMode.HTML,
                )

        m = re.search(r'^/ban (\d+)$', text)
        if m:
            reviewed_user_id = int(m.group(1))
            userinfo = Userinfo(reviewed_user_id)

            if userinfo.exists:
                userinfo.update_status(STATUS.BANNED)
                update.message.reply_text(
                    '已禁止 {} 的申請'.format(userinfo.format_full()),
                    parse_mode=telegram.ParseMode.HTML,
                )
            else:
                update.message.reply_text(
                    '{} 從未申請過，無法封鎖'.format(userinfo.format_user_id()),
                    parse_mode=telegram.ParseMode.HTML,
                )

        m = re.search(r'^/(grant|revoke)[_ ](grant|review)$', text)
        if m:
            action = m.group(1)
            permission = m.group(2)
            required_permissions = {
                'grant': PERMISSION.SUPER,
                'review': PERMISSION.GRANT,
            }
            given_permission = {
                'grant': PERMISSION.GRANT,
                'review': PERMISSION.REVIEW,
            }

            if required_permissions[permission] not in admininfo.get_permissions():
                update.message.reply_text(
                    '您沒有足夠權限進行此操作',
                )
                return

            if update.message.reply_to_message:
                reply_to_message = update.message.reply_to_message
                target_user_id = reply_to_message.from_user.id

                userinfo = Userinfo(target_user_id)

                userinfo.update_name(reply_to_message.from_user.full_name, reply_to_message.from_user.username)

                if action == 'grant':
                    userinfo.grant(given_permission[permission])
                    update.message.reply_text(
                        '已成功授予 {} {} 權限'.format(
                            userinfo.format_full(),
                            given_permission[permission],
                        ),
                        parse_mode=telegram.ParseMode.HTML,
                    )
                elif action == 'revoke':
                    userinfo.revoke(given_permission[permission])
                    update.message.reply_text(
                        '已成功除去 {} {} 權限'.format(
                            userinfo.format_full(),
                            given_permission[permission],
                        ),
                        parse_mode=telegram.ParseMode.HTML,
                    )
                else:
                    self.log('unknown action')
            else:
                update.message.reply_text(
                    '需回應訊息以授權/除權',
                )


if __name__ == "__main__":
    system = System()
    system.log('test')
