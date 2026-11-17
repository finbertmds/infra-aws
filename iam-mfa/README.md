# Triển khai MFA cho IAM users trên AWS Free Plan

Thư mục này triển khai mẫu `Force_MFA` của AWS cho một nhóm IAM users. Bắt đầu với một test user, xác minh cả đăng ký thiết bị và truy cập sau MFA, rồi mới cân nhắc thêm người dùng khác. [Hướng dẫn Force_MFA của AWS](https://docs.aws.amazon.com/IAM/latest/UserGuide/tutorial_users-self-manage-mfa-and-creds.html#tutorial_mfa_step1)

## Tài khoản AWS Projects

Với tài khoản tạo qua **Sign up for AWS (new)**, SCP do AWS quản lý có thể chặn `iam:CreateGroup`, `iam:AttachGroupPolicy`, `iam:AddUserToGroup` và các thao tác login profile. `preflight` kiểm tra account và Free Plan. Nếu một thao tác IAM trả về explicit deny từ SCP, dừng quy trình nhóm tại đó. Chuyển sang Console hoặc cấp thêm IAM permissions vẫn chịu SCP. AWS yêu cầu nâng cấp trước khi kích hoạt advanced features. [SCP của AWS Projects](https://docs.aws.amazon.com/accounts/latest/reference/scps-and-rcps-for-projects.html) · [Điều kiện kích hoạt advanced features](https://docs.aws.amazon.com/accounts/latest/reference/activate-advanced-features.html)

Để giữ Free Plan và bảo vệ danh tính đăng nhập project, vào **AWS Builder ID → Security → Register device** và cấu hình MFA. Project account do Builder ID sở hữu và không có root user để đăng nhập. Dùng mục Root MFA bên dưới cho tài khoản có root user. [MFA cho AWS Builder ID](https://docs.aws.amazon.com/signin/latest/userguide/mfa-builder-id.html) · [Root user và project accounts](https://docs.aws.amazon.com/accounts/latest/reference/root-user.html)

## Chuẩn bị

- Bash, AWS CLI v2 có lệnh `aws freetier get-account-plan-state`, và AWS CLI profile đã xác thực với tài khoản đích. Script gọi AWS CLI với region `ap-southeast-2`. Các ví dụ chạy từ thư mục gốc repo.
- Account ID 12 chữ số và Free Plan ở trạng thái `FREE / ACTIVE`, còn credits. Profile cần đọc được trạng thái Free Plan và có quyền IAM tương ứng với từng bước. Nếu thấy `AccessDenied`, kiểm tra quyền của profile và SCP nếu tài khoản chịu SCP. Nếu AWS yêu cầu nâng cấp, kích hoạt tính năng trả phí hoặc xác nhận chi phí bổ sung, dừng.
- Một phiên quản trị độc lập có quyền gỡ membership hoặc tháo policy, để khôi phục nếu test user bị khóa. Giữ phiên này ngoài nhóm triển khai.

Kiểm tra profile và tài khoản bằng bước chỉ đọc:

```bash
profile=default
account=450114866570  # Thay bằng account ID đích
bash iam/deploy.sh "$profile" preflight "account=$account"
```

Script đối chiếu account ID từ STS với Free Tier. Với mỗi bước ghi, script hiển thị lệnh dự kiến và yêu cầu nhập đúng tên bước. Sau xác nhận, script kiểm tra lại account và Free Plan, thực hiện một lệnh ghi, rồi đọc lại kết quả. Chạy từng dòng riêng để kiểm tra kết quả giữa các bước.

### Root MFA

Chủ tài khoản đăng nhập bằng **Root user**, kiểm tra **Security credentials → Multi-factor authentication (MFA)** và tự đăng ký passkey hoặc authenticator app. Xác minh đường khôi phục trước khi thay đổi, thử đăng nhập lại với thiết bị đã đăng ký, và chuẩn bị thiết bị dự phòng độc lập. Policy triển khai ở đây áp dụng cho thành viên của IAM group. IAM identity policy không hạn chế root của tài khoản standalone. [Thiết lập MFA cho root](https://docs.aws.amazon.com/IAM/latest/UserGuide/enable-mfa-for-root.html) · [Khôi phục MFA](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa_lost-or-broken.html)

## 1. Tạo policy và gắn vào nhóm

```bash
bash iam/deploy.sh "$profile" create-policy "account=$account"
bash iam/deploy.sh "$profile" create-group "account=$account"
bash iam/deploy.sh "$profile" attach-policy "account=$account"
```

- `create-policy` tạo customer-managed policy `enforce-mfa-policy`. [File JSON mẫu](./enforce-mfa-policy.json) dùng wildcard ở phần account của IAM ARN. Script thay wildcard bằng account ID đã truyền trong bản JSON gửi cho AWS, giữ nguyên file mẫu và biến IAM `${aws:username}`.
- `create-group` tạo `mfa-required-users`. `attach-policy` hiển thị default version đang có trên AWS rồi gắn policy vào nhóm trống. Nếu tài nguyên cùng tên đã tồn tại, kiểm tra nội dung và thành viên hiện có trước khi tiếp tục. Script không cập nhật version policy đã tồn tại.
- Policy dùng explicit `Deny` với `NotAction` và `BoolIfExists` cho các request có MFA context là `false` hoặc vắng mặt. User vẫn có thể đăng ký thiết bị đầu tiên. Sau khi đăng nhập lại có MFA, policy cho phép tự quản lý mật khẩu, MFA, access keys, chứng chỉ và SSH/Git credentials theo mẫu AWS. Quyền truy cập tài nguyên công việc cần được cấp riêng. Script không tạo access key. [JSON mẫu AWS](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_examples_aws_my-sec-creds-self-manage.html)

## 2. Chuẩn bị test user

Chạy bước tạo user, rồi cấp quyền đọc dùng để kiểm thử:

```bash
bash iam/deploy.sh "$profile" create-test-user "account=$account"
bash iam/deploy.sh "$profile" grant-test-read "account=$account"
```

Script tạo `mfa-test-user` và gắn inline policy `MFAReadProbe`, chỉ cấp `iam:ListAccountAliases`. Nếu đã có user trùng tên, kiểm tra đúng đó là user thử nghiệm trước khi cấp quyền hoặc thêm vào nhóm.

Trong IAM Console, cấp login profile cho test user sau khi duyệt riêng. Đăng nhập bằng test user và hoàn tất đổi mật khẩu khởi tạo **trước khi** thêm vào nhóm. Từ phiên test user này, xác nhận request `iam:ListAccountAliases` thành công trước khi áp dụng policy. Kết quả có thể là danh sách alias trống. Đây là kết quả đối chứng cho bước sau.

Sau khi đổi mật khẩu và xác nhận phép đối chứng:

```bash
bash iam/deploy.sh "$profile" add-test-user "account=$account"
```

Kiểm tra đầu ra có nhóm `mfa-required-users`.

## 3. Kiểm thử Console và CLI

| Tình huống | Kết quả mong đợi |
| --- | --- |
| Test user đã vào nhóm, phiên chưa có MFA | Request `iam:ListAccountAliases` trả `AccessDenied`. Khi thử qua Console, xác nhận trang thực sự gửi request này, vì các request khác trên trang IAM cũng có thể bị chặn. |
| Đăng ký thiết bị đầu tiên | Vào **Security credentials → Assign MFA device** bằng phiên test user. Đăng ký passkey hoặc authenticator app trực tiếp trong Console. |
| Đăng nhập lại với MFA | Đăng xuất rồi đăng nhập lại với thiết bị vừa đăng ký. `iam:ListAccountAliases` thành công. `iam:ListUsers` vẫn bị từ chối nếu test user chỉ có quyền thử nghiệm. |

Nếu dự định dùng `aws login`, kiểm thử bằng test user trước. Việc cấp quyền Sign-In phù hợp, chẳng hạn `SignInLocalDevelopmentAccess`, cần duyệt riêng. Dùng một phiên trình duyệt đã đăng nhập MFA, chọn đúng test user rồi chạy:

```bash
aws login --profile mfa-pilot
aws --profile mfa-pilot sts get-caller-identity
aws --profile mfa-pilot iam list-account-aliases
```

Đối chiếu account và ARN của test user từ STS. API `get-caller-identity` vẫn có thể thành công khi bị explicit deny, nên dùng kết quả `list-account-aliases` để xác minh quyền. Policy cũng có thể chặn bước OAuth của `aws login` nếu request thiếu MFA context. Nếu luồng CLI cần dùng bị chặn, kiểm tra quyền Sign-In, SCP và MFA trước khi mở rộng áp dụng. [AWS CLI login](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html) · [GetCallerIdentity](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)

Nếu cần kiểm thử luồng CLI dùng **access key test đã được duyệt**, request trực tiếp với key phải bị từ chối. Với thiết bị TOTP, thử lại cùng API bằng credential tạm thời từ `sts:GetSessionToken` có MFA. Giữ mã MFA và credential ngoài terminal log, Git và file cấu hình dùng chung. [GetSessionToken với MFA](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa_sample-code.html)

## 4. Mở rộng và rollback

Sau khi pilot thành công và đường khôi phục đã được kiểm chứng, có thể duyệt riêng việc thêm từng IAM user thật vào nhóm qua Console. Xác minh MFA và quyền cần thiết cho từng user. Giữ EC2/Lambda execution roles, CI/CD và các danh tính máy ngoài phạm vi nhóm. Script quản lý membership của `mfa-test-user`.

Để khôi phục test user, hoặc tháo policy nếu cả nhóm bị ảnh hưởng, chọn **một** bước thích hợp và kiểm tra kết quả sau khi chạy:

```bash
bash iam/deploy.sh "$profile" remove-test-user "account=$account"
bash iam/deploy.sh "$profile" detach-policy "account=$account"
```

`remove-test-user` chỉ gỡ membership của test user. `detach-policy` gỡ MFA enforcement do policy này cung cấp cho cả nhóm. Các quyền AWS đã được cấp qua policy khác có thể hoạt động lại khi thiếu MFA. Duyệt riêng các bước dọn pilot, như xóa inline policy thử nghiệm, login profile, thiết bị hoặc user.

Nếu script báo lỗi đọc lại sau khi AWS nhận lệnh ghi, đọc lại trạng thái trên IAM Console hoặc qua CLI trước khi thử lại. Nếu báo tài nguyên đã tồn tại, đối chiếu cấu hình hiện có với cấu hình dự kiến trước khi tiếp tục.

## Kiểm tra local

```bash
bash -n iam/deploy.sh
python3 -m json.tool iam/enforce-mfa-policy.json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s iam/tests -v
```

Bộ kiểm thử dùng AWS CLI giả lập cho các tình huống xác nhận thao tác, sai account, Paid Plan và thay account ID vào JSON triển khai.
