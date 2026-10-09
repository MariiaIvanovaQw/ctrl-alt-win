import { useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { useAction, useAsync } from '../../lib/useAsync';
import { date } from '../../lib/format';
import { Alert, Button, Card, ErrorNote, Loading, PageHeader } from '../../components/ui';
import type { GuardianView } from '../../api/types';

/**
 * Страница законного представителя несовершеннолетнего кандидата. Вход не
 * нужен: доступ по ссылке из письма. Здесь представитель даёт согласие,
 * отказывает или отзывает данное ранее. После отказа или отзыва ссылка
 * перестаёт действовать: снова дать согласие можно только по новому
 * запросу кандидата.
 */
export default function GuardianConsent() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const view = useAsync(
    () => (token ? api.anon.get<GuardianView>('/guardian-consent', { token }) : Promise.resolve(null)),
    [token],
  );
  const decide = useAction(async (decision: 'grant' | 'decline' | 'revoke') => {
    view.set(await api.anon.post<GuardianView>('/guardian-consent', { token, decision }));
  });

  if (!token) {
    return (
      <div className="pub-narrow">
        <Alert tone="warn" title="Нет ссылки">
          Откройте страницу по ссылке из письма
        </Alert>
      </div>
    );
  }
  if (view.loading) return <Loading rows={3} />;
  if (view.error) {
    return (
      <div className="pub-narrow">
        {view.error.code === 'guardian_link_invalid' ? (
          <Alert tone="warn" title="Ссылка больше не действует">
            Согласие по ней уже отозвано или кандидат запросил его заново. Если вы хотите дать согласие,
            попросите кандидата отправить новый запрос из профиля
          </Alert>
        ) : (
          <ErrorNote error={view.error} />
        )}
      </div>
    );
  }
  const v = view.data;
  if (!v) return null;
  const who = v.candidate_age ? `${v.candidate_name}, ${v.candidate_age} лет` : v.candidate_name;

  return (
    <div className="pub-narrow stack">
      <PageHeader
        title="Согласие законного представителя"
        subtitle={`${v.guardian_name}, вас указали законным представителем кандидата: ${who}`}
      />

      <Card title="На что вы соглашаетесь">
        <ul className="stack-sm" style={{ fontSize: 'var(--text-sm)' }}>
          {v.what.map((line) => (
            <li key={line}>– {line};</li>
          ))}
        </ul>
        <p className="faint" style={{ fontSize: 'var(--text-xs)', marginTop: 'var(--sp-3)' }}>
          Тест и категория доступны кандидату и без вашего согласия: это оценка навыков, а не
          трудоустройство. Трудовой договор с несовершеннолетним заключается по правилам ТК РФ
        </p>
      </Card>

      <ErrorNote error={decide.error} />

      {v.status === 'granted' ? (
        <Card title="Согласие дано">
          <p style={{ fontSize: 'var(--text-sm)' }}>
            Профиль кандидата могут видеть работодатели. Отозвать согласие можно в любой момент – профиль
            сразу скроется
          </p>
          <div style={{ marginTop: 'var(--sp-4)' }}>
            <Button busy={decide.busy} onClick={() => void decide.run('revoke')}>
              Отозвать согласие
            </Button>
          </div>
        </Card>
      ) : v.link_closed ? (
        <Alert tone="info" title={v.status === 'declined' ? 'Вы отказали в согласии' : 'Согласие отозвано'}>
          Профиль кандидата скрыт от работодателей. Эта ссылка больше не действует: чтобы дать согласие,
          попросите кандидата отправить новый запрос из профиля
        </Alert>
      ) : v.link_expired ? (
        <Alert tone="warn" title="Срок ссылки истёк">
          Ссылка действовала до {date(v.expires_at)}. Попросите кандидата отправить запрос заново из
          профиля
        </Alert>
      ) : (
        <Card
          title={
            v.status === 'pending'
              ? 'Ваше решение'
              : v.status === 'declined'
                ? 'Вы отказали в согласии'
                : 'Согласие отозвано'
          }
        >
          <div className="row-wrap">
            <Button variant="primary" busy={decide.busy} onClick={() => void decide.run('grant')}>
              Даю согласие
            </Button>
            {v.status === 'pending' && (
              <Button busy={decide.busy} onClick={() => void decide.run('decline')}>
                Не даю согласия
              </Button>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
