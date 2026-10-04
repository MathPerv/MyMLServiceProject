### Пайплайн для своего сервиса

Ссылка на прогон: https://github.com/MathPerv/MyMLServiceProject/actions/runs/37210586031

Ссылка на страницу пакета с образом: https://github.com/MathPerv/MyMLServiceProject/pkgs/container/behavior-service/1334606937?tag=sha-395a248e56bfdeff5088bee17045bf8396f23b6c

### Процесс: ветка и pull request

Ссылка на pull request: https://github.com/MathPerv/MyMLServiceProject/pull/4

### Три красных прогона с диагнозом

1. Конфиг. 
   
   Ссылка на красный прогон: https://github.com/MathPerv/MyMLServiceProject/actions/runs/37210123773

   Ссылка на зеленый прогон: https://github.com/MathPerv/MyMLServiceProject/actions/runs/37210586031

   Красным является job service на deploy. Не удается поднять нужное количество подов с нужным образом, падает в Crash Loop, т.к. внутри происходит ошибка: сервис пытается подгрузить несуществующую модель. Понять можно на job diagnostic, там выводится текст ошибки, где написано, что нужной модели нет.

2. Секрет.

   Ссылка на красный прогон: https://github.com/MathPerv/MyMLServiceProject/actions/runs/37212085487

   Ссылка на зеленый прогон: https://github.com/MathPerv/MyMLServiceProject/actions/runs/37212117750

   Падает на job service в deploy. Понять можно по ошибке CreateContainerConfigError.

3. Ресурсы.

   Ссылка на красный прогон: https://github.com/MathPerv/MyMLServiceProject/actions/runs/37210308877

   Ссылка на зеленый прогон: https://github.com/MathPerv/MyMLServiceProject/actions/runs/37210586031

   Падает на job service в deploy. Понять можно по тому, что все поды стоят в Pending.

### Ответы на вопросы

1. В первый раз build собрался успешно за 1 минуту, далее собирался по ~20 секунд.

   https://github.com/MathPerv/MyMLServiceProject/actions/runs/36589199528 - первая успешная сборка

   https://github.com/MathPerv/MyMLServiceProject/actions/runs/36589825670 - вторая

   Из кэша берутся все этапы сборки docker-образа, кроме загрузки базового образа. Связано это с тем, что в Dockerfile ничего не менялось.

2. Kubernetes пытается подтянуть поды с образами, пока образы подтягиваются из ghcr. Поэтому поды падают с ошибкой ImagePullBackOff.

3. На этапе deploy на job'е load secrets из секретов пароль загружается в в переменную среды DB_PASSWORD, а затем через envFrom он попадает в секреты. Нельзя пароль положить в configmap.yaml, т.к. тогда его смогут украсть.

4. build будет работать параллельно с tests. У нас может собраться образ, который работает некорректно и валится на тестах.

5. За это отвечают строки if: github.ref == 'refs/heads/main' и needs: build. Сделано это для того, чтобы не собирать в лишний раз образ, это имеет смысл только для main.

6. Мы поднимаем несколько образов postgres. Если они будут одновременно выполнять создание таблицы, то одна копия успеет ее создать, а вторая получит duplicate key value violates unique constraint. Связано это с тем, что volume у нас один. Эта строка гарантирует, что одновременно будет выполняться только одна команда CREATE TABLE.

7. При завышенных ресурсах все упало в статусе Pending, при указании неверной модели упало в статусе CrashLoopBackOff , при создании секретов упало на CreateContainerConfigError. Порядок такой: Pending, CreateContainerConfigError, CrashLoopBackOff. Pending возникает на этапе выделение ресурсов под под; CreateContainerConfigError возникает при попытке поднять под, но на него уже выделены ресурсы; CrashLoopBackOff - под поднялся и работает, но там происходит ошибка, он падает, поднимается его реплика и так по новой.

